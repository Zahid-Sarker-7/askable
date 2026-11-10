"""Output guardrails — check answer quality after LLM generation.

Faithfulness check: LLM-as-judge scores how grounded the answer is in the
retrieved context (0.0 = hallucination, 1.0 = fully supported).

Runs after streaming completes so it never delays token delivery to the user.
A low score emits a {type: warning} SSE event the frontend can display.
If the judge itself fails (retired model, rate limit, unparsable output) the score
is None, never 1.0: an unavailable check must not pass as "faithful".
"""

import asyncio
import logging
from groq import Groq

log = logging.getLogger("askable.guardrails.output")

# gpt-oss is a reasoning model: low effort + room for reasoning tokens before the number.
FAITHFULNESS_MODEL = "openai/gpt-oss-20b"
FAITHFULNESS_SYSTEM_PROMPT = (
    "You are a faithfulness checker for a RAG system. "
    "Given an answer and the context it was based on, rate how well the answer "
    "is supported by the context. "
    "Respond with ONLY a single decimal number between 0.0 and 1.0. "
    "1.0 = answer is fully grounded in the context. "
    "0.0 = answer contains claims not present in the context (hallucination). "
    "Do not explain. Only output the number."
)


def is_idk_response(answer: str) -> bool:
    """Return True if the LLM already declined to answer — skip faithfulness check."""
    lower = answer.lower()
    return (
        "couldn't find the answer" in lower
        or "could not find the answer" in lower
        or "i don't know" in lower
        or "i do not know" in lower
    )


def parse_score(text: str | None) -> float | None:
    """Parse the judge's reply into 0.0–1.0, or None if it isn't a number."""
    try:
        return max(0.0, min(1.0, float((text or "").strip())))
    except ValueError:
        return None


def _check_faithfulness_sync(answer: str, context: str) -> float | None:
    """Ask the LLM to score groundedness. Returns 0.0–1.0, or None if unparsable."""
    client = Groq()
    response = client.chat.completions.create(
        model=FAITHFULNESS_MODEL,
        max_completion_tokens=400,
        reasoning_effort="low",
        messages=[
            {"role": "system", "content": FAITHFULNESS_SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nAnswer:\n{answer}"},
        ],
    )
    score = parse_score(response.choices[0].message.content)
    if score is None:
        log.error("[FAITHFULNESS] unparsable judge output: %r", response.choices[0].message.content)
    else:
        log.info("[FAITHFULNESS] score=%.2f", score)
    return score


async def check_output_faithfulness(answer: str, context: str, executor) -> float | None:
    """Async wrapper — runs faithfulness check in thread; None means "couldn't check"."""
    loop = asyncio.get_event_loop()
    try:
        score = await loop.run_in_executor(
            executor, _check_faithfulness_sync, answer, context
        )
        return score
    except Exception as e:
        log.error("[FAITHFULNESS] check failed: %s", e)
        return None
