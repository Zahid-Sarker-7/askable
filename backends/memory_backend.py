"""In-process retrieval backend — hybrid search with no external services.

This is the drop-in alternative to ElasticsearchBackend for the free, single-
container demo (HF Spaces). It keeps the whole pipeline identical — same
`hybrid_search(...)` signature, same result shape — but stores everything in RAM:

    self._chunks : list of {chunk_id, content, embedding (np.ndarray), metadata}

Retrieval mirrors the ES backend exactly:
    dense kNN (cosine)  +  BM25 (keyword)  ──fuse with RRF──▶ top_k

Everything except the three marked steps in `hybrid_search` is done for you.
Those three steps are the learning core (they re-implement, in numpy + rank_bm25,
what Elasticsearch does for you). See the TODOs.

Trade-offs vs ES: linear scan (fine for thousands of chunks, not millions),
no persistence (uploads live only until restart), single process.
"""

import logging

import numpy as np
from rank_bm25 import BM25Okapi

log = logging.getLogger("askable.backends.memory")


def _tokenize(text: str) -> list[str]:
    """Cheap whitespace/lowercase tokenizer for BM25 (matches nothing fancy)."""
    return text.lower().split()


class MemoryBackend:
    """Async-compatible in-process hybrid search backend."""

    def __init__(self):
        self._chunks: list[dict] = []
        # Lazily-built search structures, invalidated on every write.
        self._matrix: np.ndarray | None = None   # (N, dim), L2-normalized rows
        self._bm25: BM25Okapi | None = None
        self._dirty = True

    # -- lifecycle (no-ops: nothing to create, nothing to flush) --

    async def ensure_index(self) -> None:
        log.info("MemoryBackend ready (in-process hybrid index)")

    async def refresh(self) -> None:
        # ES needs a refresh to make writes searchable; in-process writes are
        # visible immediately. Nothing to do.
        return None

    # -- writes ---------------------------------------------------

    async def upsert(self, chunk_id: str, text: str, embedding: list[float], metadata: dict) -> None:
        self._chunks.append({
            "chunk_id": chunk_id,
            "content": text,
            "embedding": np.asarray(embedding, dtype=np.float32),
            "metadata": metadata,
        })
        self._dirty = True

    async def delete_by_doc_id(self, doc_id: str) -> int:
        before = len(self._chunks)
        self._chunks = [c for c in self._chunks if c["metadata"].get("doc_id") != doc_id]
        deleted = before - len(self._chunks)
        if deleted:
            self._dirty = True
            log.info("Deleted %d chunks for doc_id=%s", deleted, doc_id)
        return deleted

    # -- reads ----------------------------------------------------

    async def count(self) -> int:
        return len(self._chunks)

    async def current_version(self, doc_id: str) -> int:
        """Highest version stored for this doc_id, or 0 if not present."""
        versions = [c["metadata"].get("version", 0) for c in self._chunks
                    if c["metadata"].get("doc_id") == doc_id]
        return max(versions) if versions else 0

    async def get_distinct_metadata(self, field: str) -> list[str]:
        return sorted({c["metadata"].get(field) for c in self._chunks
                       if c["metadata"].get(field) is not None})

    async def list_documents(self, session_id: str | None = None) -> list[dict]:
        """One record per unique doc_id, optionally scoped to an owner."""
        docs: dict[str, dict] = {}
        for c in self._chunks:
            m = c["metadata"]
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

    # -- internal search structures -------------------------------

    def _rebuild(self) -> None:
        """(Re)build the normalized embedding matrix + BM25 index after writes."""
        if not self._chunks:
            self._matrix, self._bm25 = None, None
            self._dirty = False
            return
        mat = np.vstack([c["embedding"] for c in self._chunks]).astype(np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        self._matrix = mat / np.clip(norms, 1e-12, None)   # unit rows → dot == cosine
        self._bm25 = BM25Okapi([_tokenize(c["content"]) for c in self._chunks])
        self._dirty = False

    def _candidate_indices(self, owners: list[str] | None) -> list[int]:
        """Positions in self._chunks whose owner is in `owners` (all if None)."""
        if not owners:
            return list(range(len(self._chunks)))
        owner_set = set(owners)
        return [i for i, c in enumerate(self._chunks)
                if c["metadata"].get("owner") in owner_set]

    def _result(self, idx: int, score: float) -> dict:
        """Shape a stored chunk into the same result dict the ES backend returns."""
        c = self._chunks[idx]
        return {"content": c["content"], "metadata": c["metadata"], "score": float(score)}

    # -- the core: hybrid search ----------------------------------

    async def hybrid_search(
        self,
        query: str,
        embedding: list[float],
        top_k: int = 10,
        owners: list[str] | None = None,
        rrf_k: int = 60,
    ) -> list[dict]:
        """BM25 + dense kNN with Reciprocal Rank Fusion — the in-process twin of
        ElasticsearchBackend.hybrid_search.

        Steps:
          1. dense kNN  — cosine similarity of the query vector vs every candidate
          2. BM25       — keyword relevance of the query terms vs every candidate
          3. RRF        — fuse the two rankings, return the top_k

        `owners` scopes the candidate set (session_id and/or "public").
        """
        if self._dirty:
            self._rebuild()
        if not self._chunks:
            return []

        candidates = self._candidate_indices(owners)
        if not candidates:
            return []

        candidate_k = top_k * 2

        # ── STEP 1 · Dense kNN ranking ──────────────────────────────────────
        # Cosine similarity of the query vs every chunk. self._matrix rows are
        # already L2-normalized, so once we normalize the query vector too, the
        # dot product IS the cosine. One matmul scores all N chunks at once.
        q = np.asarray(embedding, dtype=np.float32)
        q /= np.linalg.norm(q) + 1e-12
        sims = self._matrix @ q                      # shape (N,), one score per chunk
        # Keep only in-scope chunks, then order them best-first by similarity.
        dense_ranked = sorted(candidates, key=lambda i: sims[i], reverse=True)[:candidate_k]

        # ── STEP 2 · BM25 keyword ranking ───────────────────────────────────
        # BM25 scores every chunk on keyword overlap with the query terms.
        bm25_scores = self._bm25.get_scores(_tokenize(query))   # shape (N,)
        bm25_ranked = sorted(candidates, key=lambda i: bm25_scores[i], reverse=True)[:candidate_k]

        # ── STEP 3 · Reciprocal Rank Fusion ─────────────────────────────────
        # Fuse the two rankings by RANK, not raw score (their scales differ).
        # A chunk at 1-based rank r in a list contributes 1/(rrf_k + r); we sum
        # those contributions across both lists. Identical to the ES backend.
        fused: dict[int, float] = {}
        for ranked in (dense_ranked, bm25_ranked):
            for rank, idx in enumerate(ranked, start=1):
                fused[idx] = fused.get(idx, 0.0) + 1.0 / (rrf_k + rank)

        top = sorted(fused, key=lambda i: fused[i], reverse=True)[:top_k]
        results = [self._result(idx, fused[idx]) for idx in top]

        log.info("[MEM HYBRID] query=%r candidates=%d dense=%d bm25=%d fused=%d owners=%s",
                 query[:60], len(candidates), len(dense_ranked), len(bm25_ranked),
                 len(results), owners)
        return results
