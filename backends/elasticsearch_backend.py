"""Elasticsearch backend — async, dense vector + BM25 + hybrid RRF.

Uses AsyncElasticsearch (from elasticsearch.asyncio) so all I/O is native
async — no run_in_executor needed. The event loop handles ES calls directly.
"""

import asyncio
import logging
from elasticsearch import AsyncElasticsearch

log = logging.getLogger("askable.backends.elasticsearch")

INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "content":          {"type": "text", "analyzer": "standard"},
            "embedding":        {"type": "dense_vector", "dims": 384, "index": True, "similarity": "cosine"},
            "doc_id":           {"type": "keyword"},
            "chunk_index":      {"type": "integer"},
            "source":           {"type": "keyword"},
            "source_title":     {"type": "keyword"},
            "doc_type":         {"type": "keyword"},
            "owner":            {"type": "keyword"},
            "author":           {"type": "keyword"},
            "version":          {"type": "integer"},
            "date":             {"type": "keyword"},
            "parent_text":      {"type": "text", "index": False},
            "parent_id":        {"type": "keyword"},
            "ingested_at":      {"type": "keyword"},
        }
    }
}


class ElasticsearchBackend:
    """Async unified search backend: dense + sparse + hybrid in one HTTP call."""

    def __init__(self, url: str, index: str):
        # AsyncElasticsearch is the async version — all methods return coroutines.
        # No run_in_executor needed: the event loop drives ES I/O natively.
        self.client = AsyncElasticsearch(url)
        self.index = index

    async def ensure_index(self):
        """Create the index if it doesn't exist. Called once at startup."""
        if not await self.client.indices.exists(index=self.index):
            await self.client.indices.create(index=self.index, mappings=INDEX_MAPPING["mappings"])
            log.info("Created index: %s", self.index)
        log.info("ElasticsearchBackend ready: index=%s", self.index)

    async def upsert(self, chunk_id: str, text: str, embedding: list[float], metadata: dict) -> None:
        doc = {"content": text, "embedding": embedding, **metadata}
        await self.client.index(index=self.index, id=chunk_id, document=doc)

    async def delete_by_doc_id(self, doc_id: str) -> int:
        response = await self.client.delete_by_query(
            index=self.index,
            query={"term": {"doc_id": doc_id}},
            refresh=True,
        )
        deleted = response["deleted"]
        log.info("Deleted %d chunks for doc_id=%s", deleted, doc_id)
        return deleted

    def _build_filter(self, owners: list[str] | None) -> list[dict]:
        """Scope retrieval to a set of owners (session_id and/or 'public')."""
        if not owners:
            return []
        return [{"terms": {"owner": owners}}]

    def _hits_to_results(self, hits: list[dict]) -> list[dict]:
        return [
            {
                "content": h["_source"]["content"],
                "metadata": {k: v for k, v in h["_source"].items() if k != "content"},
                "score": h["_score"],
                "_id": h["_id"],
            }
            for h in hits
        ]

    async def hybrid_search(
        self,
        query: str,
        embedding: list[float],
        top_k: int = 10,
        owners: list[str] | None = None,
        rrf_k: int = 60,
    ) -> list[dict]:
        """BM25 + kNN hybrid search with Python-side RRF fusion.

        Runs BM25 and kNN as two separate queries, then fuses their rankings
        with Reciprocal Rank Fusion in Python. This works on the free ES Basic
        licence — the native `rrf` retriever requires a paid/trial licence.

        owners scopes results to those owner values (session_id and/or 'public').
        """
        es_filters = self._build_filter(owners)
        candidate_k = top_k * 2

        # -- BM25 query --
        bm25_query: dict = {"match": {"content": query}}
        if es_filters:
            bm25_query = {"bool": {"must": {"match": {"content": query}}, "filter": es_filters}}

        # -- kNN query --
        knn_query: dict = {
            "field": "embedding",
            "query_vector": embedding,
            "k": candidate_k,
            "num_candidates": 100,
        }
        if es_filters:
            knn_query["filter"] = {"bool": {"filter": es_filters}}

        # Run both searches concurrently
        bm25_resp, knn_resp = await asyncio.gather(
            self.client.search(
                index=self.index, query=bm25_query, size=candidate_k,
                source={"excludes": ["embedding"]},
            ),
            self.client.search(
                index=self.index, knn=knn_query, size=candidate_k,
                source={"excludes": ["embedding"]},
            ),
        )

        bm25_hits = self._hits_to_results(bm25_resp["hits"]["hits"])
        knn_hits = self._hits_to_results(knn_resp["hits"]["hits"])

        # -- Reciprocal Rank Fusion --
        # score(doc) = sum over lists of 1 / (rrf_k + rank_in_list)
        fused: dict[str, dict] = {}
        for ranked in (bm25_hits, knn_hits):
            for rank, doc in enumerate(ranked, start=1):
                key = doc["_id"]
                if key not in fused:
                    fused[key] = {**doc, "score": 0.0}
                fused[key]["score"] += 1.0 / (rrf_k + rank)

        results = sorted(fused.values(), key=lambda d: d["score"], reverse=True)[:top_k]
        for r in results:
            r.pop("_id", None)

        log.info("[ES HYBRID] query=%r bm25=%d knn=%d fused=%d owners=%s",
                 query[:60], len(bm25_hits), len(knn_hits), len(results), owners)
        return results

    async def count(self) -> int:
        response = await self.client.count(index=self.index)
        return response["count"]

    async def current_version(self, doc_id: str) -> int:
        """Highest stored version for this doc_id, or 0 if not present."""
        try:
            response = await self.client.search(
                index=self.index, size=1,
                query={"term": {"doc_id": doc_id}},
                source=["version"],
            )
            hits = response["hits"]["hits"]
            if hits:
                return hits[0]["_source"].get("version", 0)
        except Exception:
            pass
        return 0

    async def refresh(self) -> None:
        """Force the index to make recent writes searchable immediately.

        ES refreshes every ~1s by default. Call this after an interactive
        upload so the new document appears in list_documents without a race.
        """
        await self.client.indices.refresh(index=self.index)

    async def get_distinct_metadata(self, field: str) -> list[str]:
        response = await self.client.search(
            index=self.index,
            size=0,
            aggs={"values": {"terms": {"field": field, "size": 100}}},
        )
        return [b["key"] for b in response["aggregations"]["values"]["buckets"]]

    async def list_documents(self, session_id: str | None = None) -> list[dict]:
        """Return one metadata record per unique document owned by a session.

        Uses a terms aggregation on doc_id (group by document) with a top_hits
        sub-aggregation (one sample chunk's metadata) and a value_count (chunk
        count). When session_id is given, only that owner's docs are returned.
        """
        aggs = {
            "docs": {
                "terms": {"field": "doc_id", "size": 100},
                "aggs": {
                    "meta": {
                        "top_hits": {
                            "size": 1,
                            "_source": ["doc_id", "source", "source_title",
                                        "doc_type", "owner", "ingested_at", "version"],
                        }
                    },
                    "chunk_count": {"value_count": {"field": "doc_id"}},
                },
            }
        }
        search_kwargs: dict = {"index": self.index, "size": 0, "aggs": aggs}
        if session_id:
            search_kwargs["query"] = {"term": {"owner": session_id}}

        response = await self.client.search(**search_kwargs)
        results = []
        for bucket in response["aggregations"]["docs"]["buckets"]:
            src = bucket["meta"]["hits"]["hits"][0]["_source"]
            results.append({
                "doc_id": src["doc_id"],
                "source_title": src.get("source_title", src.get("source", "unknown")),
                "source": src.get("source", ""),
                "doc_type": src.get("doc_type", ""),
                "owner": src.get("owner", ""),
                "ingested_at": src.get("ingested_at", ""),
                "version": src.get("version", 1),
                "chunk_count": int(bucket["chunk_count"]["value"]),
            })
        return results
