"""Backend singletons — initialized once at startup via initialize().

Backends are async (ES and Redis use native async clients).
The embedding model is sync (CPU-bound) — initialized in a thread at startup.

Call await initialize() once from the FastAPI lifespan before serving requests.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

# NOTE: sentence_transformers (which pulls in torch) is imported LAZILY inside
# initialize(), only for the es/memory profiles. The upstash profile embeds
# server-side and must stay torch-free so it fits a Vercel serverless function.
from models import (
    BACKEND,
    EMBEDDING_MODEL,
    ES_INDEX,
    ES_URL,
    REDIS_URL,
    UPSTASH_VECTOR_REST_TOKEN,
    UPSTASH_VECTOR_REST_URL,
)

_embedding_model = None      # SentenceTransformer | None (None for the upstash profile)
_search_backend = None
_cache_backend = None
_lock = asyncio.Lock()

# Shared thread pool for CPU-bound work (ML inference)
# ProcessPoolExecutor would give true parallelism but requires picklable objects.
# ThreadPoolExecutor is simpler and still helps since PyTorch releases the GIL
# during its internal C++ operations.
executor = ThreadPoolExecutor(max_workers=4)


async def initialize():
    """Initialize all backends. Call once at application startup (FastAPI lifespan)."""
    global _embedding_model, _search_backend, _cache_backend

    async with _lock:
        if _search_backend is not None:
            return  # already initialized

        loop = asyncio.get_event_loop()

        if BACKEND == "upstash":
            # Serverless profile: Upstash embeds server-side, so we load NO local
            # model (stays torch-free for Vercel). Persistent store → no boot-ingest;
            # sample docs are ingested once via `make ingest-upstash`.
            from backends.upstash_backend import UpstashBackend
            from backends.null_cache import NullCache
            _search_backend = UpstashBackend(
                url=UPSTASH_VECTOR_REST_URL, token=UPSTASH_VECTOR_REST_TOKEN
            )
            await _search_backend.ensure_index()
            _cache_backend = NullCache()
            await _cache_backend.ensure_index()
            return

        # es + memory profiles need the local embedding model (imports torch).
        from sentence_transformers import SentenceTransformer
        _embedding_model = await loop.run_in_executor(
            executor, SentenceTransformer, EMBEDDING_MODEL
        )

        if BACKEND == "memory":
            # In-process profile (single-container, no infra): no ES, no Redis.
            from backends.memory_backend import MemoryBackend
            from backends.null_cache import NullCache
            _search_backend = MemoryBackend()
            await _search_backend.ensure_index()
            _cache_backend = NullCache()
            await _cache_backend.ensure_index()

            # The in-process index is empty at boot and can't be populated by a
            # separate `make ingest` process (different memory), so ingest the
            # public sample docs here, in-process, at startup.
            await _boot_ingest_samples()
        else:
            # Elasticsearch + Redis profile (local dev / prod).
            from backends.elasticsearch_backend import ElasticsearchBackend
            _search_backend = ElasticsearchBackend(url=ES_URL, index=ES_INDEX)
            await _search_backend.ensure_index()

            from backends.redis_cache import RedisCache
            _cache_backend = RedisCache(url=REDIS_URL)
            await _cache_backend.ensure_index()


async def _boot_ingest_samples():
    """Ingest the public sample docs into the in-process backend at startup.

    Only used by the memory backend. Skips work if the docs/ dir is missing.
    """
    import logging
    import os

    log = logging.getLogger("askable.backends")
    from ingest import DOCS_DIR, load_local_documents, _ingest_docs

    if not os.path.isdir(DOCS_DIR):
        log.warning("No %s/ dir — skipping sample ingest (memory backend empty)", DOCS_DIR)
        return

    documents = load_local_documents(DOCS_DIR)
    count = await _ingest_docs(_search_backend, _embedding_model, documents)
    log.info("Memory backend boot-ingest: %d chunks from %d sample docs", count, len(documents))


def get_embedding_model():
    """Return the shared embedding model (es/memory profiles). Must call initialize() first.

    Not available in the upstash profile (embeddings are server-side)."""
    if _embedding_model is None:
        raise RuntimeError(
            "No local embedding model — either backends aren't initialized, or "
            "BACKEND=upstash (server-side embeddings)."
        )
    return _embedding_model


def get_search_backend():
    """Return the shared Elasticsearch backend. Must call initialize() first."""
    if _search_backend is None:
        raise RuntimeError("Backends not initialized — call await initialize() at startup")
    return _search_backend


def get_cache_backend():
    """Return the shared Redis cache backend. Must call initialize() first."""
    if _cache_backend is None:
        raise RuntimeError("Backends not initialized — call await initialize() at startup")
    return _cache_backend
