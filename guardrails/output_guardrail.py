"""Output guardrails — check answer quality after LLM generation.

Faithfulness check: LLM-as-judge scores how grounded the answer is in the
retrieved context (0.0 = hallucination, 1.0 = fully supported).

Runs after streaming completes so it never delays token delivery to the user.
A low score emits a {type: warning} SSE event the frontend can display.
"""

import asyncio
import logging
from groq import Groq

log = logging.getLogger("askable.guardrails.output")

FAITHFULNESS_MODEL = "llama-3.1-8b-instant"
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
    return "i don't know" in lower or "i do not know" in lower


def _check_faithfulness_sync(answer: str, context: str) -> float:
    """Ask the LLM to score groundedness. Returns 0.0–1.0."""
    client = Groq()
    response = client.chat.completions.create(
        model=FAITHFULNESS_MODEL,
        max_tokens=10,
        messages=[
            {"role": "system", "content": FAITHFULNESS_SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nAnswer:\n{answer}"},
        ],
    )
    response_text = response.choices[0].message.content.strip()
    try:
        score = float(response_text)
    except ValueError:
        score = 1.0
    score = max(0.0, min(1.0, score))
    log.info("[FAITHFULNESS] score=%.2f", score)
    return score


async def check_output_faithfulness(answer: str, context: str, executor) -> float:
    """Async wrapper — runs faithfulness check in thread, returns score 0.0–1.0."""
    loop = asyncio.get_event_loop()
    try:
        score = await loop.run_in_executor(
            executor, _check_faithfulness_sync, answer, context
        )
        return score
    except Exception as e:
        log.warning("[FAITHFULNESS] check failed, assuming faithful: %s", e)
        return 1.0
