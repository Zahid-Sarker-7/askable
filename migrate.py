"""Migrate existing ChromaDB data into Elasticsearch.

Reads all chunks from the local ChromaDB store (including their stored
embeddings — no re-encoding needed) and writes them into Elasticsearch
using the ElasticsearchBackend adapter.

Usage:
    python migrate.py

Prerequisites:
    make infra   ← Elasticsearch must be running
"""

import logging
import sys

import chromadb

from backends.elasticsearch_backend import ElasticsearchBackend
from models import CHROMA_DIR, COLLECTION_NAME, ES_INDEX, ES_URL

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("askable.migrate")


def migrate():
    # -- Source: ChromaDB ----------------------------------------
    log.info("Connecting to ChromaDB at %s (collection: %s)", CHROMA_DIR, COLLECTION_NAME)
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception:
        print(f"Error: ChromaDB collection '{COLLECTION_NAME}' not found.")
        print("Run 'make ingest' first to populate ChromaDB.")
        sys.exit(1)

    total = collection.count()
    log.info("Found %d chunks in ChromaDB", total)
    if total == 0:
        print("ChromaDB is empty — run 'make ingest' first.")
        sys.exit(1)

    # -- Target: Elasticsearch -----------------------------------
    log.info("Connecting to Elasticsearch at %s (index: %s)", ES_URL, ES_INDEX)
    backend = ElasticsearchBackend(url=ES_URL, index=ES_INDEX)

    # -- Migrate -------------------------------------------------
    # Fetch all chunks with embeddings (no re-encoding needed)
    data = collection.get(include=["documents", "metadatas", "embeddings"])
    ids = data["ids"]
    documents = data["documents"]
    metadatas = data["metadatas"]
    embeddings = data["embeddings"]

    log.info("Migrating %d chunks...", len(ids))
    errors = 0

    for i, (chunk_id, text, metadata, embedding) in enumerate(
        zip(ids, documents, metadatas, embeddings)
    ):
        try:
            backend.upsert(
                chunk_id=chunk_id,
                text=text,
                embedding=embedding,
                metadata=metadata,
            )
        except Exception as e:
            log.error("Failed to upsert chunk %s: %s", chunk_id, e)
            errors += 1

        if (i + 1) % 10 == 0 or (i + 1) == len(ids):
            print(f"  {i + 1}/{len(ids)} chunks migrated...", end="\r")

    print()  # newline after progress

    # -- Verify --------------------------------------------------
    # Refresh ES index so count is accurate
    backend.client.indices.refresh(index=ES_INDEX)
    es_count = backend.count()
    chroma_count = total

    print(f"\n=== Migration complete ===")
    print(f"  ChromaDB chunks:       {chroma_count}")
    print(f"  Elasticsearch chunks:  {es_count}")
    print(f"  Errors:                {errors}")

    if es_count == chroma_count and errors == 0:
        print("  ✓ Counts match — migration successful")
    else:
        print("  ✗ Count mismatch or errors — check logs above")
        sys.exit(1)


if __name__ == "__main__":
    migrate()
