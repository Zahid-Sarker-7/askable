import hashlib
import os
from datetime import datetime, timezone


# -- ChromaDB (Phase A/B — kept for migration and benchmarks) ----
CHROMA_DIR = "chroma_db"
COLLECTION_NAME = "askable"

# -- Retrieval backend selection ---------------------------------
# "elasticsearch" → ES + Redis (local dev / prod). Needs the infra services.
# "memory"        → in-process hybrid index (numpy kNN + BM25), no services.
# "upstash"       → Upstash Vector (serverless hybrid, server-side embeddings).
#                   Torch-free — used for the free serverless deploy (Vercel).
BACKEND = os.getenv("BACKEND", "elasticsearch")

# -- Upstash Vector (serverless hybrid backend) ------------------
# Create a HYBRID index in the Upstash console with hosted dense + sparse
# embedding models, then set these from its REST credentials.
UPSTASH_VECTOR_REST_URL = os.getenv("UPSTASH_VECTOR_REST_URL", "")
UPSTASH_VECTOR_REST_TOKEN = os.getenv("UPSTASH_VECTOR_REST_TOKEN", "")

# -- Elasticsearch (Phase C — unified dense + sparse backend) ----
ES_URL = os.getenv("ES_URL", "http://localhost:9200")
ES_INDEX = os.getenv("ES_INDEX", "askable")

# -- Redis (Phase C — semantic query cache) ----------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))        # 1 hour
CACHE_THRESHOLD = float(os.getenv("CACHE_THRESHOLD", "0.95"))  # cosine similarity

# -- Embedding ---------------------------------------------------
# Default: English-only model (cached, works offline).
# For Bengali / multilingual, switch to "paraphrase-multilingual-MiniLM-L12-v2"
# (same 384 dims, ES mapping unchanged) once it's downloaded, then run `make reindex`.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_DIM = 384                    # both models output 384 dims

# -- Chunking ----------------------------------------------------
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

PARENT_CHUNK_SIZE = 1000
PARENT_CHUNK_OVERLAP = 100
CHILD_CHUNK_SIZE = 250
CHILD_CHUNK_OVERLAP = 25


def generate_doc_id(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()[:16]


def build_chunk_metadata(
    doc_id: str,
    chunk_index: int,
    source: str,
    source_title: str = "",
    doc_type: str = "local_doc",
    date: str = "",
    author: str = "unknown",
    owner: str = "public",
    version: int = 1,
) -> dict:
    """owner = "public" for shared/base docs, or a session_id for private uploads."""
    return {
        "doc_id": doc_id,
        "chunk_index": chunk_index,
        "source": source,
        "source_title": source_title or source.split("/")[-1].replace(".txt", "").replace("-", " ").title(),
        "doc_type": doc_type,
        "date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "author": author,
        "owner": owner,
        "version": version,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
