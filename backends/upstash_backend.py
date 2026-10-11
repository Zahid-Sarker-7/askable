"""Upstash Vector backend — serverless hybrid search with server-side embeddings.

The third retrieval adapter (alongside ElasticsearchBackend and MemoryBackend).
Upstash is a serverless vector DB that embeds text for you: you create a HYBRID
index in the Upstash console with hosted dense + sparse models, then upsert/query
with RAW TEXT — Upstash produces the dense + sparse vectors and fuses them (RRF).

Because embeddings happen server-side, this backend needs no torch / sentence-
transformers, so it deploys as a light Vercel Python function. `server_side_embeddings
= True` tells rag.py to skip the local encode() and the cross-encoder rerank.

The index must already exist (create it in the console). Set:
    UPSTASH_VECTOR_REST_URL, UPSTASH_VECTOR_REST_TOKEN
"""

import logging

from upstash_vector import AsyncIndex, Vector

log = logging.getLogger("askable.backends.upstash")


class UpstashBackend:
    """Serverless hybrid backend. Text in, ranked results out — no local models."""

    # rag.py checks this: skip local embedding + skip cross-encoder rerank.
    server_side_embeddings = True

    def __init__(self, url: str, token: str):
        self.index = AsyncIndex(url=url, token=token)

    async def ensure_index(self) -> None:
        """Sanity-check the connection (the index is created in the console)."""
        info = await self.index.info()
        log.info("UpstashBackend ready: %d vectors", info.vector_count)

    def _owner_filter(self, owners: list[str] | None) -> str:
        """Upstash metadata filter string scoping to a set of owners.

        e.g. owners=['public','sess1'] -> "owner IN ('public', 'sess1')"
        Empty string = no filter (searches everything — never do that from the API).
        """
        if not owners:
            return ""
        quoted = ", ".join(f"'{o}'" for o in owners)
        return f"owner IN ({quoted})"

    def _result(self, r) -> dict:
        """Shape an Upstash QueryResult into our standard result dict."""
        md = r.metadata or {}
        return {"content": md.get("content", ""), "metadata": md, "score": r.score}

    # -- writes ---------------------------------------------------

    async def upsert(self, chunk_id: str, text: str, embedding: list[float], metadata: dict) -> None:
        """Store one chunk. `embedding` is ignored — Upstash embeds `text` server-side.

        We stash the chunk text in metadata['content'] so query results can rebuild
        the context (Upstash returns metadata, not the original text, on query).
        """
        # TODO(zahid): upsert a single Vector with server-side embedding.
        #   Build the vector with raw text as `data` (Upstash embeds it), and put
        #   the text into metadata so we can read it back on query:
        #     vec = Vector(id=chunk_id, data=text, metadata={**metadata, "content": text})
        #     await self.index.upsert([vec])
        raise NotImplementedError("implement UpstashBackend.upsert")

    async def delete_by_doc_id(self, doc_id: str) -> int:
        """Delete every chunk of a document. Chunk ids are '<doc_id>_chunk_<i>',
        so a prefix delete removes them all in one call."""
        res = await self.index.delete(prefix=f"{doc_id}_chunk_")
        deleted = getattr(res, "deleted", 0)
        log.info("Deleted %s chunks for doc_id=%s", deleted, doc_id)
        return deleted

    async def refresh(self) -> None:
        return None  # Upstash writes are visible without an explicit refresh

    # -- the core: hybrid search ----------------------------------

    async def hybrid_search(
        self,
        query: str,
        embedding: list[float] | None = None,
        top_k: int = 10,
        owners: list[str] | None = None,
        rrf_k: int = 60,
    ) -> list[dict]:
        """Server-side hybrid search. `embedding` is unused (Upstash embeds `query`).

        Upstash runs dense + sparse retrieval and fuses them internally, so this is
        a single call — no local kNN/BM25/RRF needed.
        """
        # TODO(zahid): run the hybrid query and shape the results.
        #   Use raw text (Upstash embeds it) and scope with the owner filter:
        #     results = await self.index.query(
        #         data=query, top_k=top_k, include_metadata=True,
        #         filter=self._owner_filter(owners),
        #     )
        #     return [self._result(r) for r in results]
        raise NotImplementedError("implement UpstashBackend.hybrid_search")

    # -- reads ----------------------------------------------------

    async def count(self) -> int:
        info = await self.index.info()
        return info.vector_count

    async def current_version(self, doc_id: str) -> int:
        """Highest stored version for this doc_id, or 0 if not present."""
        results = await self.index.query(
            data=doc_id, top_k=1, include_metadata=True,
            filter=f"doc_id = '{doc_id}'",
        )
        if results:
            return (results[0].metadata or {}).get("version", 0)
        return 0

    async def _scan_all(self) -> list[dict]:
        """Page through the whole index via range(), returning metadata dicts."""
        out: list[dict] = []
        cursor = ""
        while True:
            res = await self.index.range(cursor=cursor, limit=100, include_metadata=True)
            for v in res.vectors:
                if v.metadata:
                    out.append(v.metadata)
            cursor = res.next_cursor
            if not cursor:
                break
        return out

    async def get_distinct_metadata(self, field: str) -> list[str]:
        return sorted({m.get(field) for m in await self._scan_all() if m.get(field) is not None})

    async def list_documents(self, session_id: str | None = None) -> list[dict]:
        """One record per unique doc_id, optionally scoped to an owner."""
        docs: dict[str, dict] = {}
        for m in await self._scan_all():
            if session_id is not None and m.get("owner") != session_id:
                continue
            doc_id = m.get("doc_id")
            if doc_id not in docs:
                docs[doc_id] = {
                    "doc_id": doc_id,
                    "source_title": m.get("source_title", m.get("source", "unknown")),
                    "source": m.get("source", ""),
                    "doc_type": m.get("doc_type", ""),
                    "owner": m.get("owner", ""),
                    "ingested_at": m.get("ingested_at", ""),
                    "version": m.get("version", 1),
                    "chunk_count": 0,
                }
            docs[doc_id]["chunk_count"] += 1
        return list(docs.values())
