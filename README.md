---
title: Askable
emoji: 📄
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Askable

**Upload a document and ask questions about it — get answers grounded only in that
document, streamed word-by-word, with citations.**

Askable is a production-style **Retrieval-Augmented Generation (RAG)** system built as an
end-to-end reference: hybrid retrieval, reranking, context compression, per-session
isolation, guardrails, semantic caching, and token streaming — with a Next.js chat UI.

🔗 **Live demo:** _add your Vercel URL_ · 🧠 **Design deep-dive:** [ARCHITECTURE.md](ARCHITECTURE.md)

---

## What it does

- **Ask your own docs.** Upload PDF / TXT / DOCX and query them in plain English.
- **Grounded, cited answers.** The model answers *only* from retrieved passages; if the
  answer isn't in your document, it says so. Sources are shown under each answer.
- **Streaming.** Tokens appear as they're generated (SSE), like a chat app should feel.
- **No document? Try samples.** A built-in demo knowledge base lets anyone test instantly.

## Features

| Area | What's implemented |
|------|--------------------|
| Retrieval | **Hybrid search** — dense kNN + BM25 fused with **Reciprocal Rank Fusion** (k=60) |
| Ranking | Cross-encoder **reranker** over the fused candidates |
| Strategies | `standard`, **HyDE**, **multi-query** (behind an Advanced toggle) |
| Chunking | **Semantic** + parent-document retrieval (small chunks to search, large to answer) |
| Context | LLM **context compression** before generation |
| Isolation | Per-session `owner` scoping — a session only sees its own uploads (+ samples if opted in) |
| Caching | **Semantic** query cache (Redis) for public queries |
| Safety | Input + output **guardrails** (faithfulness scoring after streaming) |
| Pluggable backend | `elasticsearch` (prod) or `memory` (in-process, zero-infra) via one env var |

## How it works

```
  question ──▶ embed ──▶ hybrid search (dense kNN + BM25 → RRF)
                              │
                              ▼
                      cross-encoder rerank ──▶ compress ──▶ LLM ──▶ stream tokens + sources
```

The LLM never answers from memory — Askable retrieves the most relevant passages first
and constrains the model to answer only from them. Full walkthrough with diagrams in
[ARCHITECTURE.md](ARCHITECTURE.md).

## Tech stack

| Layer | Choice |
|-------|--------|
| Frontend | Next.js 16, React 19, TypeScript (SSE via `fetch` + `ReadableStream`) |
| API | FastAPI (async), Server-Sent Events |
| Retrieval | Elasticsearch 9 (dense + BM25) — or in-process numpy kNN + `rank_bm25` |
| Cache | Redis Stack (RediSearch vector index) |
| Embeddings | `all-MiniLM-L6-v2` (384-dim) · Reranker: `ms-marco-MiniLM-L-6-v2` |
| LLM | Groq `llama-3.1-8b-instant` |
| Eval | RAGAS regression suite |

---

## Two backend profiles

Askable ships one pipeline with two interchangeable retrieval backends (chosen by the
`BACKEND` env var):

| | **Memory profile** | **Elasticsearch profile** |
|---|---|---|
| Retrieval | in-process (numpy kNN + BM25) | Elasticsearch (dense + BM25) |
| Cache | none (`NullCache`) | Redis semantic cache |
| Infra needed | **none** | Docker (ES + Redis) |
| Sample docs | auto-ingested at startup | `make ingest` (manual) |
| Uploads persist restart | no (in-RAM) | yes (ES volume) |
| Use it for | quick demo, the free hosted Space | full/prod, benchmarking |

## Run locally

Prereqs: Python 3.11, Node 20+, a `GROQ_API_KEY` (`cp .env.example .env` and fill it in).

### Memory profile (zero infra)

```bash
make dev-memory          # backend [:8000, BACKEND=memory] + frontend [:3000]
# backend only:  make backend-memory
```
Sample docs are ingested automatically on boot — no `make ingest`, no Docker.

### Elasticsearch profile (full stack)

```bash
make infra               # 1. start Elasticsearch + Redis (Docker)
make ingest              # 2. index the sample docs (owner="public")
make dev                 # 3. backend [:8000] + frontend [:3000]
```

Infra / data commands:

| Command | What it does |
|---------|--------------|
| `make infra-down` | stop ES + Redis (keep data volumes) |
| `make infra-nuke` | stop and **delete** all data volumes |
| `make infra-logs` | tail ES + Redis logs |
| `make ingest` | index `docs/` into ES as `owner="public"` |
| `make reindex` | wipe ES index + Redis cache, then re-ingest (after changing the embedding model) |
| `make stop` | kill anything on ports 8000 / 3000 |

> The `memory` profile has nothing to re-index — restart and the sample docs rebuild from
> `docs/` at boot. `make reindex` is ES-only.

## Configuration

| Env var | Purpose |
|---------|---------|
| `GROQ_API_KEY` | **required** — Groq API key for the LLM |
| `BACKEND` | `memory` (in-process) or `elasticsearch` |
| `FRONTEND_ORIGIN` | deployed frontend URL (e.g. `https://askable.vercel.app`) for CORS |
| `NEXT_PUBLIC_API_URL` | (frontend) backend base URL; defaults to `http://localhost:8000` |

See [.env.example](.env.example) for the full list.

## Deployment (free tier)

- **Frontend → Vercel:** root directory `frontend`, set `NEXT_PUBLIC_API_URL` to the API URL.
- **Backend → Hugging Face Space (Docker):** this repo builds directly (`Dockerfile`,
  `app_port: 7860`, `BACKEND=memory`). Set `GROQ_API_KEY` and `FRONTEND_ORIGIN` as Space secrets.

Run the container yourself:

```bash
docker build -t askable .
docker run -p 7860:7860 -e GROQ_API_KEY=$GROQ_API_KEY askable   # BACKEND=memory baked in
```

## Project layout

```
askable/
├── main.py                 FastAPI app — endpoints, session scoping, SSE
├── rag.py                  pipeline: search → rerank → compress → generate
├── ingest.py               extract → chunk → embed → index
├── chunking.py             semantic chunking
├── compression.py          LLM context compression
├── backends/               pluggable retrieval + cache
│   ├── elasticsearch_backend.py   dense + BM25 + RRF
│   ├── memory_backend.py          in-process numpy kNN + BM25 + RRF
│   └── redis_cache.py / null_cache.py
├── guardrails/             input + output (faithfulness) checks
├── docs/                   sample knowledge base (fictional company)
├── Dockerfile              Hugging Face Space (in-memory profile)
└── frontend/               Next.js 16 chat UI
```
