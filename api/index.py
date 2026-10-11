"""Vercel Python serverless entrypoint.

Vercel serves the ASGI `app` exported here; the vercel.json rewrite routes every
request to this function. We add the repo root to sys.path so `from main import app`
resolves, and default to the upstash (serverless, torch-free) profile.
"""

import os
import sys

# repo root (parent of api/) must be importable for `main`, `rag`, `backends`, …
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Serverless deploy runs the Upstash profile unless overridden by an env var.
os.environ.setdefault("BACKEND", "upstash")

from main import app  # noqa: E402  (import after sys.path / env setup)

__all__ = ["app"]
