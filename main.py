import json
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Iterator, Protocol

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from groq import Groq
from pydantic import BaseModel
from dotenv import load_dotenv

from backends import executor, initialize
from guardrails.input_guardrail import run_input_guardrails
from guardrails.output_guardrail import check_output_faithfulness, is_idk_response
from obs import configure_json_logging
from rag import retrieve_context_with_sources, build_rag_prompt, Strategy

load_dotenv()
configure_json_logging(level="INFO")

# Configuration
MAX_TOKENS = 1024
DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."
DEFAULT_MODEL = "llama-3.1-8b-instant"
FAITHFULNESS_THRESHOLD = 0.5


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialize backends once at startup before serving any requests."""
    await initialize()
    yield


app = FastAPI(title="Askable API", version="0.1.0", lifespan=lifespan)

# The deployed frontend (Vercel) is a different origin from the API (HF Space),
# so its exact URL must be allow-listed. Set FRONTEND_ORIGIN on the Space, e.g.
# "https://askable.vercel.app". Localhost/127.0.0.1 (any port) stay allowed for dev.
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "")

app.add_middleware(
    CORSMiddleware,
    # localhost and 127.0.0.1 are DIFFERENT origins to the browser — allow both.
    # Regex also covers any localhost/127.0.0.1 port (e.g. Vercel preview uses 3000).
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_origins=[FRONTEND_ORIGIN] if FRONTEND_ORIGIN else [],
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- Models ----------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    system: str = DEFAULT_SYSTEM_PROMPT
    model: str = DEFAULT_MODEL


class Message(BaseModel):
    role: str
    content: str


class ConversationRequest(BaseModel):
    messages: list[Message]
    system: str = DEFAULT_SYSTEM_PROMPT
    model: str = DEFAULT_MODEL


class RAGRequest(BaseModel):
    query: str
    model: str = DEFAULT_MODEL
    strategy: Strategy = "standard"
    include_samples: bool = False   # also search the public sample docs
    has_uploads: bool = False       # does this session have private uploads?


# -- Port / Adapter -------------------------------------------

class LLMClientPort(Protocol):
    def stream_chat(self, messages: list[dict], model: str, max_tokens: int) -> Iterator[str]: ...


class GroqAdapter:
    def __init__(self):
        self._client = Groq()

    def stream_chat(self, messages: list[dict], model: str, max_tokens: int) -> Iterator[str]:
        stream = self._client.chat.completions.create(
            model=model, stream=True, max_tokens=max_tokens, messages=messages,
        )
        for chunk in stream:
            token = chunk.choices[0].delta.content
            if token:
                yield token


def get_llm_client() -> LLMClientPort:
    return GroqAdapter()


# -- SSE helper ------------------------------------------------

def format_sse_event(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def sse_stream(client: LLMClientPort, messages: list[dict], model: str):
    async def generate() -> AsyncGenerator[str, None]:
        try:
            for token in client.stream_chat(messages=messages, model=model, max_tokens=MAX_TOKENS):
                yield format_sse_event({"type": "token", "content": token})
            yield format_sse_event({"type": "done"})
        except Exception as e:
            yield format_sse_event({"type": "error", "message": str(e)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -- Endpoints -------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "version": app.version}


@app.post("/chat")
async def chat(req: ChatRequest, client: LLMClientPort = Depends(get_llm_client)):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    messages = [
        {"role": "system", "content": req.system},
        {"role": "user", "content": req.message},
    ]
    return sse_stream(client, messages, req.model)


@app.post("/chat/conversation")
async def chat_conversation(req: ConversationRequest, client: LLMClientPort = Depends(get_llm_client)):
    req.messages = [m for m in req.messages if m.content.strip()]
    if not req.messages:
        raise HTTPException(status_code=400, detail="Messages cannot be empty")

    messages = [{"role": "system", "content": req.system}] + [
        {"role": m.role, "content": m.content} for m in req.messages
    ]
    return sse_stream(client, messages, req.model)


@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    source_title: str = Form(default=""),
    x_session_id: str = Header(default="default"),
):
    """Ingest an uploaded file into Elasticsearch for the current session."""
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in {"pdf", "txt", "docx"}:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}. Use PDF, TXT, or DOCX.")

    max_bytes = 10 * 1024 * 1024  # 10MB
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")

    from ingest import ingest_from_bytes
    result = await ingest_from_bytes(
        content=content,
        filename=filename,
        session_id=x_session_id,
        source_title=source_title,
    )
    return result


@app.get("/documents")
async def list_documents(x_session_id: str = Header(default="default")):
    """Return all documents uploaded in this session."""
    from backends import get_search_backend
    backend = get_search_backend()
    docs = await backend.list_documents(session_id=x_session_id)
    return {"documents": docs}


@app.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    """Delete all chunks for a document from Elasticsearch."""
    from backends import get_search_backend
    backend = get_search_backend()
    deleted = await backend.delete_by_doc_id(doc_id)
    return {"deleted_chunks": deleted}


@app.get("/rag/filters")
async def get_available_filters():
    from backends import get_search_backend
    backend = get_search_backend()
    return {
        "doc_types": await backend.get_distinct_metadata("doc_type"),
        "owners": await backend.get_distinct_metadata("owner"),
    }


@app.post("/rag/query")
async def rag_query(
    req: RAGRequest,
    client: LLMClientPort = Depends(get_llm_client),
    x_session_id: str = Header(default="default"),
):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # Input guardrails — block before any retrieval runs
    blocked = await run_input_guardrails(req.query)
    if blocked:
        async def _blocked() -> AsyncGenerator[str, None]:
            yield format_sse_event({"type": "error", "message": f"Query blocked: {blocked.reason}"})
            yield format_sse_event({"type": "done"})
        return StreamingResponse(_blocked(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    # Scope retrieval to this session's uploads (+ public samples if opted in).
    # This is the isolation boundary — a session never sees another's uploads.
    #
    # When the session has no private uploads, we scope to ["public"] only.
    # That keeps the scope a shared, non-private set, so the semantic cache can
    # serve the same sample answer to everyone (see `cacheable` in rag.py).
    if req.has_uploads:
        owners = [x_session_id] + (["public"] if req.include_samples else [])
    else:
        owners = ["public"] if req.include_samples else [x_session_id]
    context, sources = await retrieve_context_with_sources(
        req.query,
        use_hyde=(req.strategy == "hyde"),
        use_multi_query=(req.strategy == "multi_query"),
        owners=owners,
    )
    messages = build_rag_prompt(req.query, context)

    async def generate() -> AsyncGenerator[str, None]:
        collected: list[str] = []
        try:
            for token in client.stream_chat(messages=messages, model=req.model, max_tokens=MAX_TOKENS):
                collected.append(token)
                yield format_sse_event({"type": "token", "content": token})

            # Output guardrail — faithfulness check after streaming completes
            full_answer = "".join(collected)
            if not is_idk_response(full_answer):
                score = await check_output_faithfulness(full_answer, context, executor)
                if score < FAITHFULNESS_THRESHOLD:
                    yield format_sse_event({
                        "type": "warning",
                        "message": f"Answer may not be fully grounded in sources (score: {score:.2f})",
                    })

            yield format_sse_event({"type": "sources", "sources": sources})
            yield format_sse_event({"type": "done"})
        except Exception as e:
            yield format_sse_event({"type": "error", "message": str(e)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
