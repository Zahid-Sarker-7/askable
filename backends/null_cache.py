"""No-op cache — used by the in-process ("memory") backend profile.

The semantic cache (Redis) is an optimization, not a correctness requirement.
In the free single-container demo there is no Redis, so we swap in a cache that
always misses. rag.py calls get()/put() unconditionally for public-only queries;
this keeps that path working without any special-casing there.
"""

import logging

log = logging.getLogger("askable.backends.null_cache")


class NullCache:
    """Implements the RedisCache interface but stores nothing."""

    async def ensure_index(self) -> None:
        log.info("NullCache active — semantic caching disabled (memory backend)")

    async def get(self, query_embedding: list[float], threshold: float | None = None) -> None:
        # Always a miss.
        return None

    async def put(
        self,
        query_embedding: list[float],
        query_text: str,
        context: str,
        sources: list[str],
        ttl: int | None = None,
    ) -> None:
        # Discard.
        return None
