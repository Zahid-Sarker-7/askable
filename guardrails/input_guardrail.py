"""Input guardrails — block bad queries before any retrieval runs.

Three checks run concurrently via asyncio.gather (no LLM needed — pure regex/keywords):
  1. PII detection    — SSN, credit card numbers, email addresses
  2. Prompt injection — attempts to override system instructions
  3. Off-topic        — queries clearly unrelated to the knowledge base

All checks are sync (CPU-only, no I/O) and run in threads via asyncio.to_thread
so they don't block the event loop.
"""

import asyncio
import re
from dataclasses import dataclass


@dataclass
class GuardrailResult:
    blocked: bool
    reason: str
    check: str  # "pii" | "injection" | "off_topic"


# -- PII detection -----------------------------------------------------------

_PII_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "SSN"),
    (re.compile(r"\b\d{4}[- ]\d{4}[- ]\d{4}[- ]\d{4}\b"), "credit card"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "email"),
]


def check_pii(query: str) -> GuardrailResult:
    for pattern, label in _PII_PATTERNS:
        if pattern.search(query):
            return GuardrailResult(
                blocked=True,
                reason=f"Query contains {label} — please remove personal information",
                check="pii",
            )
    return GuardrailResult(blocked=False, reason="", check="pii")


# -- Prompt injection detection ----------------------------------------------

def check_injection(query: str) -> GuardrailResult:
    """Detect attempts to override system instructions."""
    injection_phrases = [
        "ignore previous instructions",
        "ignore all instructions",
        "disregard the above",
        "disregard all previous",
        "you are now",
        "act as if",
        "pretend you are",
        "forget everything",
        "new persona",
        "system prompt",
    ]
    query_lower = query.lower()
    for phrase in injection_phrases:
        if phrase in query_lower:
            return GuardrailResult(
                blocked=True,
                reason="Prompt injection detected — please avoid trying to override system instructions",
                check="injection",
            )
    return GuardrailResult(blocked=False, reason="", check="injection")


# -- Off-topic detection -----------------------------------------------------

_OFF_TOPIC_KEYWORDS = {
    "movie", "film", "actor", "actress", "celebrity", "singer", "song", "album",
    "recipe", "cook", "bake", "ingredient", "weather", "forecast", "temperature",
    "sports", "score", "match", "team", "player", "football", "basketball",
    "homework", "essay", "poem", "story", "novel", "girlfriend", "boyfriend",
    "joke", "prank", "meme", "viral", "lottery", "casino", "gambling",
}


def check_off_topic(query: str) -> GuardrailResult:
    words = set(query.lower().split())
    matches = words & _OFF_TOPIC_KEYWORDS
    if len(matches) >= 2:
        return GuardrailResult(
            blocked=True,
            reason=f"Query appears off-topic (matched: {', '.join(sorted(matches))})",
            check="off_topic",
        )
    return GuardrailResult(blocked=False, reason="", check="off_topic")


# -- Orchestrator ------------------------------------------------------------

async def run_input_guardrails(query: str) -> GuardrailResult | None:
    """Run all checks concurrently. Return first blocking result, or None if all pass."""
    results = await asyncio.gather(
        asyncio.to_thread(check_pii, query),
        asyncio.to_thread(check_injection, query),
        asyncio.to_thread(check_off_topic, query),
    )
    for result in results:
        if result.blocked:
            return result
    return None
