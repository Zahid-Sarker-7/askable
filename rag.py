import asyncio
import logging
import uuid
from typing import Literal

from sentence_transformers import CrossEncoder
from groq import Groq
from dotenv import load_dotenv

from backends import executor, get_embedding_model, get_search_backend, get_cache_backend
from compression import compress_context
from latency import timed
from obs import emit

load_dotenv()

log = logging.getLogger("askable.rag")

RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
LLM_MODEL = "llama-3.1-8b-instant"
TOP_K = 10
FINAL_K = 5
MULTI_QUERY_COUNT = 3

Strategy = Literal["standard", "hyde", "multi_query"]

_reranker: CrossEncoder | None = None


def _get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(RERANKER_MODEL)
    return _reranker


# -- Retrieval (async, native ES calls) ------------------------
# `owners` scopes retrieval to a set of owner values (session_id and/or "public").
# This is the security boundary: a session only sees its own uploads (+ samples
# if opted in). Passing None searches everything — never do that from the API.

async def hybrid_search(query: str, owners: list[str] | None = None) -> list[dict]:
    """Embed query (CPU thread) + ES hybrid search (native async HTTP)."""
    loop = asyncio.get_event_loop()

    # Embedding is CPU-bound — run in thread so event loop stays free
    async with timed("embed") as t:
        embedding = await loop.run_in_executor(
            executor, get_embedding_model().encode, query
        )
    log.info("[EMBED] %.1fms", t.ms)

    # ES search is native async — no thread needed
    async with timed("es_search") as t:
        results = await get_search_backend().hybrid_search(
            query, embedding.tolist(), top_k=TOP_K, owners=owners
        )
    log.info("[ES HYBRID] query=%r hits=%d (%.1fms)", query[:80], len(results), t.ms)
    return results


async def hyde_search(query: str, owners: list[str] | None = None) -> list[dict]:
    """HyDE: generate hypothetical answer (thread) then embed + search."""
    loop = asyncio.get_event_loop()

    async with timed("hyde_llm"):
        hypothetical = await loop.run_in_executor(
            executor, generate_hypothetical_answer, query
        )
    log.info("[HyDE] hypothetical=%r", hypothetical[:100])

    async with timed("embed"):
        embedding = await loop.run_in_executor(
            executor, get_embedding_model().encode, hypothetical
        )

    async with timed("es_search") as t:
        results = await get_search_backend().hybrid_search(
            hypothetical, embedding.tolist(), top_k=TOP_K, owners=owners
        )
    log.info("[HyDE] hits=%d (%.1fms)", len(results), t.ms)
    return results


async def multi_query_search(query: str, owners: list[str] | None = None) -> list[dict]:
    """Multi-query: generate variations (thread) + search ALL in parallel."""
    loop = asyncio.get_event_loop()

    async with timed("multi_query_llm"):
        variations = await loop.run_in_executor(
            executor, generate_query_variations, query
        )

    # All searches run concurrently — this is the key speedup vs sequential
    async with timed("multi_query_search") as t:
        all_results = await asyncio.gather(
            *[hybrid_search(q, owners) for q in [query] + variations]
        )

    seen: dict[str, dict] = {}
    for result_list in all_results:
        for doc in result_list:
            if doc["content"] not in seen:
                seen[doc["content"]] = doc

    log.info("[MULTI-QUERY] %d queries -> %d unique chunks (%.1fms)",
             1 + len(variations), len(seen), t.ms)
    return list(seen.values())


# -- Reranking (CPU-bound — must use thread) -------------------

async def rerank(query: str, docs: list[dict], top_k: int = FINAL_K) -> list[dict]:
    """Cross-encoder reranking — CPU-bound, runs in thread to free event loop."""
    if not docs:
        return []

    loop = asyncio.get_event_loop()
    model = _get_reranker()
    pairs = [[query, doc["content"]] for doc in docs]

    async with timed("rerank") as t:
        scores = await loop.run_in_executor(executor, model.predict, pairs)

    for doc, score in zip(docs, scores):
        doc["rerank_score"] = float(score)

    ranked = sorted(docs, key=lambda x: x["rerank_score"], reverse=True)
    log.info("[RERANK] %d docs -> top %d best=%.3f (%.1fms)",
             len(docs), top_k, ranked[0]["rerank_score"], t.ms)
    return ranked[:top_k]


# -- LLM helpers (sync — called via run_in_executor) -----------

def generate_hypothetical_answer(query: str) -> str:
    client = Groq()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=150,
        messages=[
            {
                "role": "system",
                "content": (
                    "Write a short paragraph that would answer the following question. "
                    "Write it as if it appeared in a company document. "
                    "Do not say 'I don't know'. Just write a plausible answer."
                ),
            },
            {"role": "user", "content": query},
        ],
    )
    return response.choices[0].message.content.strip()


def generate_query_variations(query: str) -> list[str]:
    client = Groq()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=200,
        messages=[
            {
                "role": "system",
                "content": (
                    f"Generate exactly {MULTI_QUERY_COUNT} alternative phrasings of the following question. "
                    "Each should approach the topic from a different angle. "
                    "Return ONLY the questions, one per line, numbered 1. 2. 3."
                ),
            },
            {"role": "user", "content": query},
        ],
    )
    variations = []
    for line in response.choices[0].message.content.splitlines():
        line = line.strip()
        if line and line[0].isdigit() and "." in line:
            variations.append(line.split(".", 1)[1].strip())
    log.info("[MULTI-QUERY] generated %d variations for %r", len(variations), query[:80])
    return variations


# -- Main Pipeline (fully async) -------------------------------

async def retrieve_context_with_sources(
    query: str,
    use_hyde: bool = False,
    use_multi_query: bool = False,
    owners: list[str] | None = None,
) -> tuple[str, list[str]]:
    query_id = uuid.uuid4().hex[:8]
    strategy = "hyde" if use_hyde else ("multi_query" if use_multi_query else "standard")
    emit(log, "pipeline_start", query_id=query_id, strategy=strategy, owners=owners)

    loop = asyncio.get_event_loop()

    # Embed query for cache lookup — reused if cache miss
    async with timed("embed_query") as t:
        query_embedding = await loop.run_in_executor(
            executor, get_embedding_model().encode, query
        )
        query_embedding_list = query_embedding.tolist()

    # Only cache public-only queries. A query scoped to a private session must
    # never be served from (or written to) the shared semantic cache, or Session
    # B could receive Session A's cached answer.
    cacheable = owners == ["public"]

    if cacheable:
        async with timed("cache_check"):
            cached = await get_cache_backend().get(query_embedding_list)
        if cached:
            emit(log, "cache_result", query_id=query_id, hit=True)
            return cached["context"], cached["sources"]
        emit(log, "cache_result", query_id=query_id, hit=False)

    # Retrieval
    async with timed("retrieval"):
        if use_hyde:
            candidates = await hyde_search(query, owners=owners)
        elif use_multi_query:
            candidates = await multi_query_search(query, owners=owners)
        else:
            candidates = await hybrid_search(query, owners=owners)

    # Rerank
    reranked = await rerank(query, candidates)
    if reranked:
        emit(log, "rerank_scores", query_id=query_id,
             top_score=round(reranked[0].get("rerank_score", 0), 3),
             bottom_score=round(reranked[-1].get("rerank_score", 0), 3),
             num_docs=len(reranked))

    # Parent-doc dedup + context build
    seen_parents: set[str] = set()
    unique = []
    for doc in reranked:
        pid = doc["metadata"].get("parent_id")
        if pid and pid in seen_parents:
            continue
        if pid:
            seen_parents.add(pid)
        unique.append(doc)
        if len(unique) >= FINAL_K:
            break

    context = "\n\n".join(d["metadata"].get("parent_text", d["content"]) for d in unique)
    sources = list({d["metadata"].get("source", "unknown") for d in unique})

    async with timed("compression"):
        context = await compress_context(query, context, executor)

    # Cache store — only for public-only queries (see cacheable above)
    if cacheable:
        asyncio.create_task(
            get_cache_backend().put(query_embedding_list, query, context, sources)
        )

    emit(log, "pipeline_end", query_id=query_id, context_len=len(context),
         num_sources=len(sources), sources=sources)

    return context, sources


def build_rag_prompt(query: str, context: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "Answer based ONLY on the context below. "
                "If the context doesn't contain the answer, say 'I don't know.'\n\n"
                f"Context:\n{context}"
            ),
        },
        {"role": "user", "content": query},
    ]
