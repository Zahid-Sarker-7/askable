"""Backend singletons — initialized once at startup via initialize().

Backends are async (ES and Redis use native async clients).
The embedding model is sync (CPU-bound) — initialized in a thread at startup.

Call await initialize() once from the FastAPI lifespan before serving requests.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from sentence_transformers import SentenceTransformer
from models import BACKEND, EMBEDDING_MODEL, ES_INDEX, ES_URL, REDIS_URL

_embedding_model: SentenceTransformer | None = None
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

        # Load embedding model in thread (slow first-time download)
        _embedding_model = await loop.run_in_executor(
            executor, SentenceTransformer, EMBEDDING_MODEL
        )

        if BACKEND == "memory":
            # In-process profile (free single-container demo): no ES, no Redis.
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


def get_embedding_model() -> SentenceTransformer:
    """Return the shared embedding model. Must call initialize() first."""
    if _embedding_model is None:
        raise RuntimeError("Backends not initialized — call await initialize() at startup")
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
