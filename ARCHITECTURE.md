# Askable — Architecture

> **What it is:** Askable lets anyone upload a document (PDF, TXT, or DOCX) and ask
> questions about it in plain English. Answers are streamed back word‑by‑word and are
> grounded **only** in the uploaded content — with citations. No document? Toggle
> "sample docs" and try it against a built‑in demo knowledge base.
>
> Under the hood it's a production‑style **RAG** (Retrieval‑Augmented Generation)
> system: hybrid search, reranking, semantic caching, session isolation, guardrails,
> and token streaming.

---

## 1. The 30‑second picture

```
                 ┌──────────────────────────────────────────────┐
                 │                   BROWSER                     │
                 │        Next.js 16 + React 19 (chat UI)        │
                 └───────────────┬──────────────────────────────┘
                                 │  HTTPS
             upload a file  ─────┤  ask a question (SSE stream back)
                                 │
                 ┌───────────────▼──────────────────────────────┐
                 │                FastAPI (Python)               │
                 │   /upload   /rag/query   /documents   /health │
                 └───────┬───────────────────────────┬──────────┘
                         │                            │
              ┌──────────▼─────────┐        ┌─────────▼──────────┐
              │   RAG PIPELINE     │        │    LLM (Groq)      │
              │ embed → search →   │        │ llama‑3.1‑8b       │
              │ rerank → compress  │        │ streams tokens     │
              └──────┬──────┬──────┘        └────────────────────┘
                     │      │
        ┌────────────▼─┐  ┌─▼───────────────┐
        │ Elasticsearch│  │  Redis Stack    │
        │ vectors+BM25 │  │ semantic cache  │
        └──────────────┘  └─────────────────┘
```

**One idea to hold onto:** the LLM never answers from memory. Askable *retrieves* the
most relevant passages from your document first, then asks the LLM to answer **using
only those passages**. That's what keeps answers accurate and citable.

---

## 2. The two things a user does

### A. Upload a document (ingestion)

```
 PDF/TXT/DOCX
     │
     ▼
 ┌─────────────┐   extract    ┌──────────────┐   split into    ┌───────────────┐
 │  raw bytes  │ ───text────▶ │  clean text  │ ──semantic────▶ │ chunks (~pieces│
 │ (fitz/docx) │              │              │   chunking      │  of meaning)  │
 └─────────────┘              └──────────────┘                 └──────┬────────┘
                                                                      │
                                              embed each chunk        │
                                            (all‑MiniLM‑L6‑v2, 384d)  ▼
                                                            ┌────────────────────┐
                                                            │  Elasticsearch     │
                                                            │  1 doc per chunk:  │
                                                            │  text + vector +   │
                                                            │  owner + metadata  │
                                                            └────────────────────┘
```

- **Semantic chunking** ([chunking.py](chunking.py)) splits on *meaning shifts*, not a
  fixed character count. It embeds each sentence and starts a new chunk where adjacent
  sentences stop being similar — so a chunk stays about one topic.
- Every chunk is stamped with an **`owner`**: `"public"` for the built‑in sample docs,
  or the caller's **`session_id`** for a private upload. This one field is the entire
  security boundary (see §6).

### B. Ask a question (retrieval + generation)

This is the request lifecycle for `POST /rag/query`:

```
  question + X-Session-ID
        │
        ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │ 1. EMBED the question  ────────────────────────────────▶ [384d vector]│
  ├──────────────────────────────────────────────────────────────────────┤
  │ 2. CACHE CHECK (only if the query is "public"-only)                    │
  │      hit  ──▶ reuse stored context, skip straight to step 6           │
  │      miss ──▶ continue                                                 │
  ├──────────────────────────────────────────────────────────────────────┤
  │ 3. HYBRID SEARCH in Elasticsearch, scoped to owner ∈ [session,public]  │
  │      • BM25 (keyword match)        ┐                                    │
  │      • kNN  (vector similarity)    ├─▶ fuse with RRF ─▶ top candidates  │
  ├──────────────────────────────────────────────────────────────────────┤
  │ 4. RERANK candidates with a cross‑encoder ─▶ keep the best 5           │
  ├──────────────────────────────────────────────────────────────────────┤
  │ 5. COMPRESS: LLM squeezes the passages down to only what's relevant    │
  │      (then cache the result if public‑only)                            │
  ├──────────────────────────────────────────────────────────────────────┤
  │ 6. GENERATE: LLM answers using ONLY that context ─▶ stream tokens (SSE)│
  ├──────────────────────────────────────────────────────────────────────┤
  │ 7. GUARDRAIL (after stream): score faithfulness; warn if ungrounded    │
  └──────────────────────────────────────────────────────────────────────┘
        │
        ▼
   answer (streamed) + sources[]
```

---

## 3. Why hybrid search (the core RAG idea)

No single search method is enough, so Askable runs two and merges them:

| Method | Good at | Blind to |
|--------|---------|----------|
| **BM25** (keyword) | exact terms, codes, names ("SOC 2", "API key") | synonyms, paraphrase |
| **kNN** (vector) | meaning & paraphrase ("how do I get money back" ≈ "refund") | rare exact tokens |
| **Hybrid (both)** | both of the above | — |

The two ranked lists are merged with **Reciprocal Rank Fusion (RRF)**:

```
score(doc) = Σ  1 / (k + rank_in_list)      # k = 60
             over each list the doc appears in
```

RRF only needs each result's *rank*, not its raw score, so it fuses two
incompatible scoring scales cleanly. Fusion is done in Python
([backends/elasticsearch_backend.py](backends/elasticsearch_backend.py)) so it runs on
the free Elasticsearch licence.

Then a **cross‑encoder reranker** ([rag.py](rag.py)) re‑reads the top candidates
*together with* the question and reorders them — slower but far more precise than the
first‑pass search, so we only run it on the shortlist.

**Optional retrieval strategies** (hidden behind "Advanced" in the UI):

| Strategy | What it adds |
|----------|--------------|
| `standard` | hybrid search as above (default) |
| `hyde` | LLM writes a hypothetical answer first, then searches with *that* — helps vague questions |
| `multi_query` | LLM rephrases the question 3 ways, searches all in parallel, dedupes |

---

## 4. Semantic cache (why the same question is instant)

A normal cache needs an *exact* key match. A **semantic** cache matches by *meaning*:
"What's the refund window?" and "How long do I have to get a refund?" hit the same entry.

```
 query embedding ──▶ Redis vector search (KNN 1, cosine) ──▶ nearest cached query
                                                              │
                              similarity ≥ 0.95 ? ──yes──▶ CACHE HIT (reuse context)
                                                └──no───▶ CACHE MISS (run pipeline, store)
```

**Crucial rule:** only **public‑only** queries are cached. A query touching a private
upload is never read from or written to the shared cache — otherwise Session B could be
served Session A's answer. This is enforced in one line in [rag.py](rag.py):
`cacheable = owners == ["public"]`.

That's also why the **sample questions are fast**: they're public‑only, so the first
person to ask populates the cache and everyone after gets an instant retrieval hit.

---

## 5. Streaming (why you see words appear)

The LLM produces tokens one at a time; Askable forwards them as they arrive using
**Server‑Sent Events (SSE)** — a one‑way stream of `data:` lines over a normal HTTP
response.

```
FastAPI  ──"data: {type:token, content:'The'}"──▶ browser  (appended live)
         ──"data: {type:token, content:' Pro'}"──▶
         ──"data: {type:sources, sources:[...]}"─▶  (shown under the answer)
         ──"data: {type:done}"─────────────────▶  (stream closed)
```

| Event | Meaning |
|-------|---------|
| `token` | one piece of the answer — append it |
| `sources` | the documents the answer came from |
| `warning` | faithfulness guardrail flagged a possibly ungrounded answer |
| `done` / `error` | stream finished / failed |

The frontend reads the stream with `fetch` + `ReadableStream` + `TextDecoder`
([frontend/src/lib/sse.ts](frontend/src/lib/sse.ts)) — no third‑party SDK.

---

## 6. Session isolation (the security model)

Every browser gets a random `session_id` (a UUID kept in `localStorage`) and sends it
as the `X-Session-ID` header. The server turns that into an `owners` scope that becomes
an Elasticsearch filter — **you can only ever retrieve chunks whose `owner` is in your
scope.**

```
 has uploads?   "try samples"?   →   owners scope (retrieval filter)
 ─────────────────────────────────────────────────────────────────
     no              off          →   [session_id]     (nothing yet → "I don't know")
     no              on           →   ["public"]       (sample docs only, cacheable)
     yes             off          →   [session_id]     (your uploads only)
     yes             on           →   [session_id, "public"]  (yours + samples)
```

Computed in [main.py](main.py); applied as a `terms` filter on `owner` in every search.
Session B literally cannot express a query that reaches Session A's chunks.

---

## 7. Guardrails

| Stage | Guardrail | Behaviour |
|-------|-----------|-----------|
| **Input** ([guardrails/input_guardrail.py](guardrails/input_guardrail.py)) | reject empty / abusive / off‑scope input before spending compute | blocks early |
| **Output** ([guardrails/output_guardrail.py](guardrails/output_guardrail.py)) | LLM‑as‑judge scores how faithful the answer is to the retrieved context | runs *after* streaming so it never delays tokens; low score → `warning` event |

The system prompt also hard‑instructs the model: *"Answer based ONLY on the context…
if it isn't there, say 'I don't know.'"* — so the default failure mode is honesty, not
hallucination.

---

## 8. Concurrency model (how one process stays fast)

FastAPI runs on a single async event loop. Askable keeps it responsive by matching each
kind of work to the right tool:

| Work | Nature | How it's run |
|------|--------|--------------|
| Elasticsearch / Redis calls | network I/O | **native async** (`AsyncElasticsearch`, `redis.asyncio`) — the loop stays free |
| Embedding / reranking (ML) | CPU‑bound | **thread pool** via `run_in_executor` — keeps the loop unblocked |
| Multi‑query searches | independent | **`asyncio.gather`** — run in parallel, not one after another |
| Heavy models (embedder, reranker) | expensive to load | **singletons** created once at startup (FastAPI `lifespan`) |

See [backends/__init__.py](backends/__init__.py) (singletons + shared executor) and
[latency.py](latency.py) (per‑stage timing that shows up in the logs).

---

## 9. Component / file map

```
askable/
├── main.py                     FastAPI app: endpoints, session→owners scope, SSE
├── rag.py                      the pipeline: search → rerank → compress → cache
├── ingest.py                   upload & local ingestion (extract → chunk → embed → index)
├── chunking.py                 semantic chunking (split on meaning shifts)
├── compression.py              LLM context compression (relevant‑only summary)
├── models.py                   config, constants, chunk metadata builder
├── obs.py                      structured JSON logging (one event per line)
├── latency.py                  async timing context manager
├── backends/
│   ├── __init__.py             singletons: embedder, reranker, ES, Redis, executor
│   ├── elasticsearch_backend.py  hybrid search (BM25 + kNN + RRF), list/delete docs
│   └── redis_cache.py          semantic cache (RediSearch vector index)
├── guardrails/
│   ├── input_guardrail.py      pre‑generation checks
│   └── output_guardrail.py     post‑generation faithfulness score
├── sources/                    Confluence / Jira ingestion adapters (optional sources)
├── evaluate.py / benchmark.py  RAGAS eval + strategy benchmarking
├── migrate.py                  one‑off ChromaDB → Elasticsearch migration
├── docker-compose.yml          Elasticsearch + Redis Stack (local infra)
├── Makefile                    infra / ingest / reindex / dev / evaluate targets
└── frontend/                   Next.js 16 + React 19
    └── src/
        ├── lib/{sse,types}.ts              SSE parsing + shared types
        └── features/chat/
            ├── components/                 ChatPage, MessageList, DocumentPanel,
            │                               EmptyState, StarterView, SourcesList, …
            └── hooks/{useRAGStream,useDocuments}.ts   streaming + document state
```

---

## 10. Tech stack at a glance

| Layer | Choice | Why |
|-------|--------|-----|
| Frontend | Next.js 16, React 19, TypeScript | modern SSR‑capable UI; native `fetch` streaming |
| API | FastAPI (async Python) | first‑class async + streaming responses |
| Retrieval store | Elasticsearch 9 | dense vectors **and** BM25 **and** filtering in one engine |
| Cache | Redis Stack (RediSearch) | vector similarity for semantic caching |
| Embeddings | `all‑MiniLM‑L6‑v2` (384d) | small, fast, runs locally/offline; env‑swappable |
| Reranker | `ms‑marco‑MiniLM‑L‑6‑v2` cross‑encoder | precise second‑pass ranking |
| LLM | Groq `llama‑3.1‑8b‑instant` | very fast token streaming |
| Eval | RAGAS | regression‑test retrieval + answer quality |

---

## 11. Two backend profiles

The retrieval store is pluggable (the `get_search_backend()` seam), selected by the
`BACKEND` env var — the rest of the pipeline is identical:

| `BACKEND=elasticsearch` (prod / local) | `BACKEND=memory` (free single-container demo) |
|---|---|
| Elasticsearch (dense + BM25) + Redis cache | in-process numpy kNN + `rank_bm25`, `NullCache` |
| needs Docker infra + `make ingest` | no infra; sample docs ingested at boot |
| uploads persist (ES volume) | uploads live in RAM (reset on restart) |

The `memory` profile re-implements exactly what ES does for us (same RRF, k=60) so the
whole app runs free in one container (Hugging Face Spaces). See
[backends/memory_backend.py](backends/memory_backend.py).

## 12. Run it locally

```bash
# Zero-infra (in-process) — fastest way to try it:
make dev-memory   # FastAPI (:8000, BACKEND=memory) + Next.js (:3000)

# Full stack (Elasticsearch + Redis):
make infra        # start ES + Redis (Docker)
make ingest       # index the sample docs as owner="public"
make dev          # FastAPI (:8000) + Next.js (:3000)
```

`make reindex` wipes the index + cache and re-ingests — needed after changing the
embedding model (ES profile only; the memory profile rebuilds from `docs/` at boot).
