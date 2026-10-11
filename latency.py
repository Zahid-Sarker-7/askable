"""Latency tracking for the RAG pipeline.

Usage:
    from latency import timed

    async with timed("dense_search") as t:
        results = await dense_search(query)
    # t.ms is the elapsed milliseconds — logged automatically
"""

import time
import logging
from contextlib import asynccontextmanager

log = logging.getLogger("askable.latency")


class Timer:
    def __init__(self, name: str):
        self.name = name
        self.ms: float = 0.0


@asynccontextmanager
async def timed(name: str):
    """Async context manager that measures elapsed time and logs it."""
    t = Timer(name)
    start = time.perf_counter()
    try:
        yield t
    finally:
        t.ms = (time.perf_counter() - start) * 1000
        log.info("[LATENCY] %s = %.1fms", name, t.ms)
