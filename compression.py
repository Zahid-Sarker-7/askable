"""Context compression — summarize retrieved chunks before final LLM generation.

Reduces token usage by extracting only the parts of the retrieved context
that are relevant to the query. Falls back to original context on failure
or when context is already short enough not to warrant compression.
"""

import asyncio
import logging

from groq import Groq

log = logging.getLogger("askable.compression")

COMPRESSION_MODEL = "llama-3.1-8b-instant"
MIN_CONTEXT_LEN = 500  # don't compress short contexts — not worth the extra LLM call

COMPRESSION_SYSTEM_PROMPT = (
    "You are a context summarizer for a RAG system. "
    "Given a user query and retrieved context passages, extract and summarize "
    "ONLY the information relevant to answering the query. "
    "Preserve specific facts, numbers, dates, and technical details verbatim. "
    "Remove irrelevant passages entirely. Be concise — your output should be "
    "significantly shorter than the input."
)


def _compress_sync(query: str, context: str) -> str:
    """Call the LLM to compress context (sync — called via run_in_executor)."""
    client = Groq()
    response = client.chat.completions.create(
        model=COMPRESSION_MODEL,
        max_tokens=400,
        messages=[
            {"role": "system", "content": COMPRESSION_SYSTEM_PROMPT},
            {"role": "user", "content": f"Query: {query}\n\nContext:\n{context}"},
        ],
    )
    return response.choices[0].message.content.strip()


async def compress_context(query: str, context: str, executor) -> str:
    """Compress retrieved context to only what's relevant to the query.

    Returns compressed context, or original if context is short or compression fails.
    """
    if len(context) < MIN_CONTEXT_LEN:
        log.info("[COMPRESSION] skipped (context too short: %d chars)", len(context))
        return context

    original_len = len(context)
    loop = asyncio.get_event_loop()

    try:
        compressed = await loop.run_in_executor(executor, _compress_sync, query, context)
        log.info(
            "[COMPRESSION] %d chars → %d chars (%.0f%% reduction)",
            original_len,
            len(compressed),
            (1 - len(compressed) / original_len) * 100,
        )
        return compressed
    except Exception as e:
        log.warning("[COMPRESSION] failed, using original context: %s", e)
        return context
