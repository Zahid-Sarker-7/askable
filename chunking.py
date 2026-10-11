import re

import numpy as np
from sentence_transformers import SentenceTransformer, util

from models import EMBEDDING_MODEL, PARENT_CHUNK_SIZE


def split_into_sentences(text: str) -> list[str]:
    raw = re.split(r'(?<=[.!?])\s+|\n{2,}', text)
    return [s.strip() for s in raw if s.strip()]


def find_breakpoints(similarities: list[float], threshold_std: float = 1.0) -> list[int]:
    mean = float(np.mean(similarities))
    std = float(np.std(similarities))
    cutoff = mean - threshold_std * std
    return [i + 1 for i, sim in enumerate(similarities) if sim < cutoff]


def group_sentences_into_chunks(
    sentences: list[str],
    breakpoints: list[int],
    max_chunk_size: int = PARENT_CHUNK_SIZE,
) -> list[str]:
    """Group sentences into chunks at the breakpoints.

    If any resulting chunk exceeds max_chunk_size, split it further by
    distributing sentences evenly.
    """
    
    chunks = []
    boundaries = [0] + breakpoints + [len(sentences)]
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        chunk_sentences = sentences[start:end]
        chunk_text = " ".join(chunk_sentences)
        if len(chunk_text) > max_chunk_size:
            mid = len(chunk_sentences) // 2
            chunks.append(" ".join(chunk_sentences[:mid]))
            chunks.append(" ".join(chunk_sentences[mid:]))
        else:
            chunks.append(chunk_text)
    return chunks


def semantic_chunk(
    text: str,
    model_name: str = EMBEDDING_MODEL,
    breakpoint_threshold: float = 1.0,
    max_chunk_size: int = PARENT_CHUNK_SIZE,
) -> list[str]:
    """Split text into semantically coherent chunks.

    Algorithm:
    1. Split into sentences
    2. Embed each sentence
    3. Compute cosine similarity between consecutive sentences
    4. Where similarity drops (topic shift), place a breakpoint
    5. Group sentences between breakpoints into chunks

    Returns a list of chunk strings.
    """
    sentences = split_into_sentences(text)
    if len(sentences) <= 1:
        return [text] if text.strip() else []

    model = SentenceTransformer(model_name)
    embeddings = model.encode(sentences)

    similarities = [
        util.cos_sim(embeddings[i], embeddings[i + 1]).item()
        for i in range(len(embeddings) - 1)
    ]

    breakpoints = find_breakpoints(similarities, breakpoint_threshold)
    chunks = group_sentences_into_chunks(sentences, breakpoints, max_chunk_size)

    return chunks
