"""Redis semantic cache — async client (redis.asyncio).

Uses redis.asyncio so all Redis I/O is native async — no run_in_executor.
"""

import json
import logging
import uuid

import numpy as np
import redis.asyncio as aioredis
from redis.commands.search.field import TextField, VectorField
from redis.commands.search.index_definition import IndexDefinition
from redis.commands.search.query import Query

from models import CACHE_THRESHOLD, CACHE_TTL, EMBEDDING_DIM, REDIS_URL

log = logging.getLogger("askable.backends.redis_cache")

CACHE_INDEX = "askable_cache_idx"
CACHE_KEY_PREFIX = "askable_cache:"


class RedisCache:
    """Async semantic query cache backed by Redis + RediSearch vector index."""

    def __init__(self, url: str = REDIS_URL):
        # redis.asyncio.from_url returns an async Redis client.
        # All methods (hset, expire, ft().search, etc.) are coroutines.
        self.client = aioredis.from_url(url, decode_responses=False)

    async def ensure_index(self):
        """Create the vector index if it doesn't exist. Called once at startup."""
        try:
            await self.client.ft(CACHE_INDEX).info()
            log.info("Redis cache index already exists")
        except Exception:
            await self.client.ft(CACHE_INDEX).create_index(
                fields=[
                    TextField("query_text"),
                    VectorField(
                        "embedding",
                        algorithm="FLAT",
                        attributes={
                            "TYPE": "FLOAT32",
                            "DIM": EMBEDDING_DIM,
                            "DISTANCE_METRIC": "COSINE",
                        },
                    ),
                ],
                definition=IndexDefinition(prefix=[CACHE_KEY_PREFIX]),
            )
            log.info("Created Redis cache index: %s", CACHE_INDEX)

    def _embedding_to_bytes(self, embedding: list[float]) -> bytes:
        return np.array(embedding, dtype=np.float32).tobytes()

    async def get(self, query_embedding: list[float], threshold: float = CACHE_THRESHOLD) -> dict | None:
        query_bytes = self._embedding_to_bytes(query_embedding)
        query = (
            Query("(*)=>[KNN 1 @embedding $vec AS score]")
            .sort_by("score", asc=True)
            .return_fields("query_text", "context", "sources", "score")
            .dialect(2)
        )
        results = await self.client.ft(CACHE_INDEX).search(
            query, query_params={"vec": query_bytes}
        )

        if not results.docs:
            log.info("[CACHE MISS] cache is empty")
            return None

        distance = float(results.docs[0].score)
        similarity = 1 - distance

        if similarity >= threshold:
            log.info("[CACHE HIT] similarity=%.3f query=%r", similarity, results.docs[0].query_text[:60])
            return {
                "context": results.docs[0].context,
                "sources": json.loads(results.docs[0].sources),
            }

        log.info("[CACHE MISS] best_similarity=%.3f", similarity)
        return None

    async def put(
        self,
        query_embedding: list[float],
        query_text: str,
        context: str,
        sources: list[str],
        ttl: int = CACHE_TTL,
    ) -> None:
        key = f"{CACHE_KEY_PREFIX}{uuid.uuid4().hex}"
        await self.client.hset(key, mapping={
            "embedding": self._embedding_to_bytes(query_embedding),
            "query_text": query_text,
            "context": context,
            "sources": json.dumps(sources),
        })
        await self.client.expire(key, ttl)
        log.info("[CACHE PUT] query=%r ttl=%ds", query_text[:60], ttl)
