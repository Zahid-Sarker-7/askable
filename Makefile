.PHONY: backend frontend dev ingest setup clean backend-memory dev-memory backend-upstash ingest-upstash

# ── Two ways to run the backend ────────────────────────────────────────
# ELASTICSEARCH profile (default): real ES + Redis. Needs `make infra` up and
#   `make ingest` to load the sample docs. This is the production/local story.
# MEMORY profile: in-process hybrid index (numpy kNN + BM25). No infra, no
#   ingest step — sample docs are ingested automatically at startup. This is
#   what the free Hugging Face Space runs.

# Start FastAPI backend — Elasticsearch profile (port 8000, auto-reload)
backend:
	.venv/bin/uvicorn main:app --reload --port 8000

# Start FastAPI backend — in-memory profile (no ES/Redis needed)
backend-memory:
	BACKEND=memory .venv/bin/uvicorn main:app --reload --port 8000

# Start FastAPI backend — Upstash serverless profile (needs UPSTASH_* env vars).
# Set them in .env or the shell; Upstash embeds server-side (no local models).
backend-upstash:
	BACKEND=upstash .venv/bin/uvicorn main:app --reload --port 8000

# One-time: ingest the sample docs into the Upstash index as owner="public".
# Upstash is persistent, so this is run once (not on every server start).
ingest-upstash:
	BACKEND=upstash .venv/bin/python ingest.py

# Start Next.js frontend (port 3000, hot module replacement)
frontend:
	cd frontend && npm run dev

# Start both backend (Elasticsearch profile) and frontend in parallel.
# Prerequisites: `make infra` and `make ingest` first.
dev:
	@echo "Starting backend [elasticsearch] (:8000) and frontend (:3000)..."
	@trap 'kill 0' EXIT; \
		$(MAKE) backend & \
		$(MAKE) frontend & \
		wait

# Start both backend (in-memory profile) and frontend — zero infra required.
dev-memory:
	@echo "Starting backend [memory] (:8000) and frontend (:3000) — no ES/Redis..."
	@trap 'kill 0' EXIT; \
		$(MAKE) backend-memory & \
		$(MAKE) frontend & \
		wait

# Index all sources into Elasticsearch
ingest:
	.venv/bin/python ingest.py

# Wipe the ES index + Redis cache, then re-ingest base docs.
# Use after changing the embedding model — old vectors live in a different
# vector space and must be regenerated.
reindex:
	@curl -s -X DELETE http://localhost:9200/askable > /dev/null && echo "Deleted ES index"
	@docker compose exec -T redis redis-cli FLUSHALL > /dev/null 2>&1 && echo "Flushed Redis cache" || true
	.venv/bin/python ingest.py

# Index individual sources
ingest-confluence:
	.venv/bin/python ingest.py --source confluence

ingest-jira:
	.venv/bin/python ingest.py --source jira

# First-time setup: create venv, install deps, index docs
setup:
	python3 -m venv .venv
	.venv/bin/pip install fastapi uvicorn groq python-dotenv pydantic \
		langchain langchain-community langchain-text-splitters \
		chromadb sentence-transformers rank-bm25 \
		atlassian-python-api beautifulsoup4 markdownify \
		qdrant-client elasticsearch redis
	cd frontend && npm install
	@echo "\nSetup complete. Create askable/.env with GROQ_API_KEY, then run: make ingest && make dev"

# Docker infrastructure (Elasticsearch + Redis)
# Hybrid search uses Python-side RRF (free Basic licence) — no trial needed.
infra:
	docker compose up -d
	@echo "Waiting for Elasticsearch to start (~30s)..."
	@until curl -sf http://localhost:9200/_cluster/health > /dev/null 2>&1; do sleep 2; done
	@echo "Elasticsearch: $$(curl -s -o /dev/null -w '%{http_code}' http://localhost:9200)"
	@echo "Redis:         $$(docker compose exec -T redis redis-cli ping 2>/dev/null || echo 'not ready')"

infra-down:
	docker compose down

infra-logs:
	docker compose logs -f

infra-nuke:
	docker compose down -v
	@echo "All data volumes deleted"

# Migrate existing ChromaDB data into Elasticsearch (run after make infra)
migrate:
	.venv/bin/python migrate.py

# RAGAS evaluation
evaluate:
	.venv/bin/python evaluate.py

eval-baseline:
	.venv/bin/python evaluate.py --save-baseline

eval-compare:
	.venv/bin/python evaluate.py --compare

# A/B benchmark: compare chunking strategies and embedding models
benchmark:
	.venv/bin/python benchmark.py

# Test backend SSE format with curl
test-sse:
	@echo "=== Chat endpoint ==="
	@curl -s --no-buffer -X POST http://localhost:8000/chat \
		-H "Content-Type: application/json" \
		-d '{"message":"Say hello in one word"}' | head -5
	@echo "\n=== RAG endpoint (last 5 lines) ==="
	@curl -s -X POST http://localhost:8000/rag/query \
		-H "Content-Type: application/json" \
		-d '{"query":"What is the refund policy?","strategy":"standard"}' | tail -5

# Stop any running servers on ports 8000 and 3000
stop:
	@lsof -ti:8000 | xargs kill -9 2>/dev/null || true
	@lsof -ti:3000 | xargs kill -9 2>/dev/null || true
	@echo "Stopped servers on ports 8000 and 3000"
