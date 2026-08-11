"""RAG Evaluation Script — RAGAS Metrics + Regression Tracking.

Usage:
    python evaluate.py                 # run evaluation, print scores
    python evaluate.py --save-baseline # save scores as new baseline
    python evaluate.py --compare       # compare against saved baseline
"""

import argparse
import asyncio
import json
import os

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_groq import ChatGroq
from langchain_community.embeddings import HuggingFaceEmbeddings
from dotenv import load_dotenv

from backends import initialize
from rag import retrieve_context_with_sources

load_dotenv()

LLM_MODEL = "llama-3.1-8b-instant"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
BASELINE_FILE = "eval_baseline.json"
REGRESSION_THRESHOLD = 0.05  # alert if any metric drops more than 5 points

METRICS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]

TEST_QUESTIONS = [
    {
        "question": "What is the refund policy for regular customers?",
        "ground_truth": "All customers are eligible for a full refund within 30 days of purchase. After 30 days, refunds are prorated based on the remaining subscription period. No refunds are issued after 90 days.",
    },
    {
        "question": "How much does the Pro plan cost?",
        "ground_truth": "The Pro plan costs $49/month or $470/year with a 20% annual discount.",
    },
    {
        "question": "What encryption does AutoMind use for data at rest?",
        "ground_truth": "All data is encrypted at rest using AES-256 encryption.",
    },
    {
        "question": "What is the on-call compensation?",
        "ground_truth": "$500/week on-call stipend plus $200 per incident handled.",
    },
    {
        "question": "What HTTP status code is returned for rate limiting?",
        "ground_truth": "429 Too Many Requests is returned when the rate limit is exceeded, with a Retry-After header indicating seconds to wait.",
    },
]


async def generate_answers() -> dict:
    """Run each test question through the async RAG pipeline and collect answers."""
    await initialize()
    llm = ChatGroq(model=LLM_MODEL)

    questions, answers, contexts, ground_truths = [], [], [], []

    for q in TEST_QUESTIONS:
        # retrieve_context_with_sources is async — must be awaited
        context, _ = await retrieve_context_with_sources(q["question"])

        messages = [
            {"role": "system", "content": f"Answer based ONLY on the context below.\n\nContext:\n{context}"},
            {"role": "user", "content": q["question"]},
        ]
        response = llm.invoke(messages)

        questions.append(q["question"])
        answers.append(response.content)
        # RAGAS expects list[list[str]] — split context into individual chunks
        contexts.append(context.split("\n\n"))
        ground_truths.append(q["ground_truth"])

    return {
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths,
    }


async def run_evaluation() -> dict:
    """Run RAGAS evaluation and return scores dict."""
    print("=== RAG Evaluation (RAGAS) ===\n")

    print("1. Generating answers from RAG pipeline...")
    results = await generate_answers()
    print(f"   Generated {len(results['question'])} answers\n")

    dataset = Dataset.from_dict(results)

    llm = LangchainLLMWrapper(ChatGroq(model=LLM_MODEL))
    embeddings = LangchainEmbeddingsWrapper(HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL))

    print("2. Running RAGAS evaluation...")
    scores = evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=llm,
        embeddings=embeddings,
    )

    print("\n=== RAGAS Scores ===")
    score_dict = {}
    for metric in METRICS:
        raw = scores[metric]
        if isinstance(raw, list):
            valid = [v for v in raw if v is not None]
            value = sum(valid) / len(valid) if valid else 0.0
        else:
            value = float(raw)
        score_dict[metric] = round(value, 4)
        status = "✓" if value >= 0.7 else "✗"
        print(f"   {status} {metric:25s} {value:.3f}")

    print("\n   Target: all scores > 0.7")
    return score_dict


# -- Regression tracking -----------------------------------------------

def save_baseline(scores: dict, filepath: str = BASELINE_FILE) -> None:
    from datetime import datetime
    payload = {"recorded_at": datetime.utcnow().isoformat(), **scores}
    with open(filepath, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nBaseline saved to {filepath}")


def load_baseline(filepath: str = BASELINE_FILE) -> dict | None:
    try:
        with open(filepath) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def compare_to_baseline(current: dict, baseline: dict) -> list[str]:
    """Return regression warnings for any metric that dropped more than REGRESSION_THRESHOLD."""
    warnings = []
    for metric in METRICS:
        if metric not in current or metric not in baseline:
            continue
        delta = current[metric] - baseline[metric]
        if delta < -REGRESSION_THRESHOLD:
            warnings.append(
                f"REGRESSION: {metric} dropped {abs(delta):.3f} "
                f"({baseline[metric]:.3f} → {current[metric]:.3f})"
            )
    return warnings


# -- Entry point -------------------------------------------------------

async def main_async():
    parser = argparse.ArgumentParser(description="Askable RAG evaluation")
    parser.add_argument("--save-baseline", action="store_true",
                        help="Save current scores as the new baseline")
    parser.add_argument("--compare", action="store_true",
                        help="Compare current scores to the saved baseline")
    args = parser.parse_args()

    scores = await run_evaluation()

    if args.save_baseline:
        save_baseline(scores)

    if args.compare:
        baseline = load_baseline()
        if baseline is None:
            print("\nNo baseline found. Run with --save-baseline first.")
        else:
            print(f"\n(Baseline recorded at: {baseline.get('recorded_at', 'unknown')})")
            warnings = compare_to_baseline(scores, baseline)
            if warnings:
                print("\n=== REGRESSIONS DETECTED ===")
                for w in warnings:
                    print(f"  {w}")
            else:
                print("\n=== All metrics held — no regressions ===")


if __name__ == "__main__":
    asyncio.run(main_async())
