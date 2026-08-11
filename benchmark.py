"""A/B benchmark — compare chunking strategies and embedding models with RAGAS.

Usage:
    python benchmark.py              # run all configs
    python benchmark.py --config bge-large  # run a single config
"""

import argparse
import logging
import time

import chromadb
from datasets import Dataset
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_groq import ChatGroq
from ragas import evaluate as ragas_evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
from sentence_transformers import SentenceTransformer

from chunking import semantic_chunk
from ingest import load_local_documents
from models import (
    CHILD_CHUNK_OVERLAP,
    CHILD_CHUNK_SIZE,
    CHROMA_DIR,
    EMBEDDING_MODEL,
    PARENT_CHUNK_OVERLAP,
    PARENT_CHUNK_SIZE,
    generate_doc_id,
)
from rag import build_rag_prompt

logging.basicConfig(level=logging.WARNING)

LLM_MODEL = "llama-3.1-8b-instant"

CONFIGS = [
    {
        "name": "baseline",
        "embedding": "all-MiniLM-L6-v2",
        "chunking": "recursive",
        "collection": "bench_baseline",
    },
    {
        "name": "semantic",
        "embedding": "all-MiniLM-L6-v2",
        "chunking": "semantic",
        "collection": "bench_semantic",
    },
    {
        "name": "bge-large",
        "embedding": "BAAI/bge-large-en-v1.5",
        "chunking": "recursive",
        "collection": "bench_bge",
    },
]

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


def _chunk_recursive(text: str) -> list[str]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=PARENT_CHUNK_SIZE, chunk_overlap=PARENT_CHUNK_OVERLAP
    )
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHILD_CHUNK_SIZE, chunk_overlap=CHILD_CHUNK_OVERLAP
    )
    chunks = []
    for parent in parent_splitter.split_text(text):
        chunks.extend(child_splitter.split_text(parent))
    return chunks


def ingest_for_config(config: dict, documents: list[dict]):
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    try:
        client.delete_collection(config["collection"])
    except Exception:
        pass
    collection = client.create_collection(
        name=config["collection"], metadata={"hnsw:space": "cosine"}
    )

    model = SentenceTransformer(config["embedding"])
    total = 0

    for doc in documents:
        doc_id = generate_doc_id(doc["source"])

        if config["chunking"] == "semantic":
            chunks = semantic_chunk(doc["text"], model_name=config["embedding"])
        else:
            chunks = _chunk_recursive(doc["text"])

        if not chunks:
            continue

        ids = [f"{doc_id}_bench_{i}" for i in range(len(chunks))]
        embeddings = model.encode(chunks).tolist()
        metadatas = [{"source": doc["source"], "doc_id": doc_id} for _ in chunks]

        collection.add(ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas)
        total += len(chunks)

    print(f"  {config['name']}: {total} chunks from {len(documents)} docs")


def evaluate_config(config: dict) -> dict:
    embeddings = HuggingFaceEmbeddings(model_name=config["embedding"])
    db = Chroma(
        persist_directory=CHROMA_DIR,
        collection_name=config["collection"],
        embedding_function=embeddings,
    )

    llm = ChatGroq(model=LLM_MODEL)
    questions, answers, contexts, ground_truths = [], [], [], []

    for q in TEST_QUESTIONS:
        results = db.similarity_search(q["question"], k=5)
        context = "\n\n".join(r.page_content for r in results)
        messages = build_rag_prompt(q["question"], context)
        answer = llm.invoke(messages).content

        questions.append(q["question"])
        answers.append(answer)
        contexts.append([context])
        ground_truths.append(q["ground_truth"])

        time.sleep(2)

    dataset = Dataset.from_dict({
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths,
    })

    ragas_llm = LangchainLLMWrapper(ChatGroq(model=LLM_MODEL))
    ragas_emb = LangchainEmbeddingsWrapper(HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL))

    scores = ragas_evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=ragas_llm,
        embeddings=ragas_emb,
    )

    result = {}
    for metric in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
        val = scores[metric]
        if isinstance(val, list):
            valid = [v for v in val if v is not None]
            result[metric] = sum(valid) / len(valid) if valid else 0.0
        else:
            result[metric] = float(val)

    print(f"  {config['name']}: {result}")
    return result


def print_comparison(results: dict[str, dict]):
    metrics = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]

    header = f"{'Config':<15} {'Chunking':<12} {'Embedding':<25}"
    for m in metrics:
        header += f" {m[:12]:>12}"
    print(header)
    print("-" * len(header))

    for name, scores in results.items():
        config = next(c for c in CONFIGS if c["name"] == name)
        row = f"{name:<15} {config['chunking']:<12} {config['embedding']:<25}"
        for m in metrics:
            val = scores.get(m, float("nan"))
            row += f" {val:>12.3f}"
        print(row)


def main():
    parser = argparse.ArgumentParser(description="A/B benchmark for RAG configurations")
    parser.add_argument("--config", help="Run a single config by name", default=None)
    args = parser.parse_args()

    configs = CONFIGS
    if args.config:
        configs = [c for c in CONFIGS if c["name"] == args.config]
        if not configs:
            print(f"Unknown config: {args.config}. Available: {[c['name'] for c in CONFIGS]}")
            return

    documents = load_local_documents("docs")
    results = {}

    for config in configs:
        print(f"\n{'='*60}")
        print(f"Config: {config['name']} (chunking={config['chunking']}, embedding={config['embedding']})")
        print(f"{'='*60}")

        print("Ingesting...")
        ingest_for_config(config, documents)

        print("Evaluating...")
        scores = evaluate_config(config)
        results[config["name"]] = scores

    print(f"\n{'='*60}")
    print("COMPARISON")
    print(f"{'='*60}\n")
    print_comparison(results)


if __name__ == "__main__":
    main()
