# Askable backend — Hugging Face Spaces (Docker SDK), free in-process profile.
#
# Runs FastAPI + the in-process hybrid index (BACKEND=memory): no Elasticsearch,
# no Redis, one container. Models are baked in at build time so cold starts are
# fast and the container needs no network except to reach the Groq API.

FROM python:3.11-slim

# --- system deps (minimal; torch/pymupdf ship manylinux wheels) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# --- non-root user (HF Spaces runs containers as uid 1000) ---
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    # model caches must live somewhere writable by the runtime user
    HF_HOME=/home/user/.cache/huggingface \
    # in-process profile: no external services required
    BACKEND=memory \
    PYTHONUNBUFFERED=1

WORKDIR /home/user/app

# --- python deps ---
# Install CPU-only torch first (default index pulls the multi-GB CUDA build).
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt

# --- app code (see .dockerignore for exclusions) ---
COPY --chown=user . .

USER user

# --- pre-download models at build time (fast, offline cold starts) ---
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('all-MiniLM-L6-v2'); \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

EXPOSE 7860

# HF Spaces routes traffic to app_port (7860, set in README frontmatter).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
