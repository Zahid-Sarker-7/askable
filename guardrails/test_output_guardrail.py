"""Run: .venv/bin/python -m guardrails.test_output_guardrail  (pytest also collects it)."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from guardrails import output_guardrail as og


def test_parse_score():
    assert og.parse_score("0.8") == 0.8
    assert og.parse_score(" 1.7 ") == 1.0  # clamped
    assert og.parse_score("") is None
    assert og.parse_score(None) is None
    assert og.parse_score("The answer is grounded.") is None  # never defaults to faithful


def test_judge_failure_is_none_not_faithful():
    def boom(*_):
        raise RuntimeError("model_not_found")

    real, og._check_faithfulness_sync = og._check_faithfulness_sync, boom
    try:
        with ThreadPoolExecutor(1) as ex:
            assert asyncio.run(og.check_output_faithfulness("a", "c", ex)) is None
    finally:
        og._check_faithfulness_sync = real


if __name__ == "__main__":
    test_parse_score()
    test_judge_failure_is_none_not_faithful()
    print("ok")
