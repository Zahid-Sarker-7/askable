import logging
import os

from langchain_text_splitters import RecursiveCharacterTextSplitter

from backends import get_embedding_model, get_search_backend
from models import (
    CHILD_CHUNK_OVERLAP,
    CHILD_CHUNK_SIZE,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    PARENT_CHUNK_OVERLAP,
    PARENT_CHUNK_SIZE,
    build_chunk_metadata,
    generate_doc_id,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("askable.ingest")

DOCS_DIR = "docs"


def _model_or_none():
    """The local embedding model, or None when the backend embeds server-side
    (upstash). Lets the ingest path stay torch-free for the serverless profile."""
    if getattr(get_search_backend(), "server_side_embeddings", False):
        return None
    return get_embedding_model()


def load_local_documents(docs_dir: str) -> list[dict]:
    files = sorted(os.listdir(docs_dir))
    log.info("Found %d files in %s: %s", len(files), docs_dir, files)

    documents = []
    for filename in files:
        filepath = os.path.join(docs_dir, filename)
        # Read directly (no langchain loaders) to keep the serverless deps light.
        if filename.endswith(".pdf"):
            import fitz  # PyMuPDF
            doc = fitz.open(filepath)
            text = "\n\n".join(page.get_text() for page in doc)
        elif filename.endswith(".txt"):
            with open(filepath, encoding="utf-8", errors="replace") as f:
                text = f.read()
        else:
            continue

        documents.append({
            "text": text,
            "source": filepath,
            "source_title": filename.replace(".txt", "").replace(".pdf", "").replace("-", " ").title(),
            "doc_type": "local_doc",
            "author": "unknown",
            "owner": "public",
        })
        log.info("Loaded %s (%d chars)", filepath, len(text))

    return documents


def chunk_text(text: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    return splitter.split_text(text)


def chunk_with_parents(text: str, doc_id: str) -> list[dict]:
    """Two-level chunking: split into large parents, then small children.

    Returns a list of dicts, one per child chunk:
      child_text  — small chunk (~250 chars) — gets embedded and searched
      parent_text — large chunk (~1000 chars) — stored in metadata, used for LLM context
      parent_id   — links sibling children to the same parent section
    """
    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=PARENT_CHUNK_SIZE, chunk_overlap=PARENT_CHUNK_OVERLAP
    )
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHILD_CHUNK_SIZE, chunk_overlap=CHILD_CHUNK_OVERLAP
    )
    results = []
    for parent_idx, parent_text in enumerate(parent_splitter.split_text(text)):
        parent_id = f"{doc_id}_parent_{parent_idx}"
        for child_text in child_splitter.split_text(parent_text):
            results.append({
                "child_text": child_text,
                "parent_text": parent_text,
                "parent_id": parent_id,
            })
    return results


async def get_current_version(backend, doc_id: str) -> int:
    """Current version of a document (0 if not found). Backend-agnostic —
    both ElasticsearchBackend and MemoryBackend implement current_version()."""
    return await backend.current_version(doc_id)


async def ingest_single_document(
    backend,
    model,
    text: str,
    source: str,
    source_title: str = "",
    doc_type: str = "local_doc",
    date: str = "",
    author: str = "unknown",
    owner: str = "public",
) -> int:
    doc_id = generate_doc_id(source)
    current_version = await get_current_version(backend, doc_id)
    new_version = current_version + 1

    if current_version > 0:
        await backend.delete_by_doc_id(doc_id)
        log.info("Deleted v%d chunks for doc_id=%s (%s)", current_version, doc_id, source)

    parent_children = chunk_with_parents(text, doc_id)
    if not parent_children:
        log.warning("No chunks produced for %s", source)
        return 0

    child_texts = [pc["child_text"] for pc in parent_children]
    ids = [f"{doc_id}_chunk_{i}" for i in range(len(child_texts))]
    # Server-side backends (upstash) embed on upsert — no local model needed.
    if getattr(backend, "server_side_embeddings", False):
        embeddings = [None] * len(child_texts)
    else:
        embeddings = model.encode(child_texts).tolist()

    for i, (chunk_id, child_text, embedding, pc) in enumerate(zip(ids, child_texts, embeddings, parent_children)):
        metadata = {
            **build_chunk_metadata(
                doc_id=doc_id,
                chunk_index=i,
                source=source,
                source_title=source_title,
                doc_type=doc_type,
                date=date,
                author=author,
                owner=owner,
                version=new_version,
            ),
            "parent_text": pc["parent_text"],
            "parent_id": pc["parent_id"],
        }
        await backend.upsert(chunk_id=chunk_id, text=child_text, embedding=embedding, metadata=metadata)

    log.info("Ingested %s: %d chunks, v%d (doc_id=%s)", source, len(child_texts), new_version, doc_id)
    return len(child_texts)


async def _ingest_docs(backend, model, documents: list[dict]) -> int:
    total = 0
    for doc in documents:
        total += await ingest_single_document(
            backend=backend,
            model=model,
            text=doc["text"],
            source=doc["source"],
            source_title=doc["source_title"],
            doc_type=doc["doc_type"],
            date=doc.get("date", ""),
            author=doc.get("author", "unknown"),
            owner=doc.get("owner", "public"),
        )
    return total


async def ingest_from_bytes(
    content: bytes,
    filename: str,
    session_id: str,
    source_title: str = "",
) -> dict:
    """Extract text from an uploaded file and ingest it into Elasticsearch.

    Supports: .pdf (PyMuPDF/fitz), .txt (UTF-8), .docx (python-docx).
    Tagged with owner=session_id for per-session isolation.
    Returns: {doc_id, chunks_indexed, source_title, filename}
    """
    file_type = filename.lower().rsplit(".", 1)[-1]
    if file_type == "pdf":
        import fitz  # PyMuPDF
        doc = fitz.open(stream=content, filetype="pdf")
        text = "\n\n".join(page.get_text() for page in doc)
    elif file_type == "txt":
        text = content.decode("utf-8", errors="replace")
    elif file_type == "docx":
        import io
        import docx
        doc = docx.Document(io.BytesIO(content))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    else:
        raise ValueError(f"Unsupported file type: {filename}")

    source = f"upload/{session_id}/{filename}"
    if not source_title:
        source_title = filename.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").title()

    backend = get_search_backend()
    chunks = await ingest_single_document(
        backend=backend,
        model=_model_or_none(),
        text=text,
        source=source,
        source_title=source_title,
        doc_type="user_upload",
        owner=session_id,
    )
    # Make the upload immediately visible to the next list_documents call
    await backend.refresh()
    return {
        "doc_id": generate_doc_id(source),
        "chunks_indexed": chunks,
        "source_title": source_title,
        "filename": filename,
    }


async def ingest_local():
    backend = get_search_backend()
    model = _model_or_none()
    documents = load_local_documents(DOCS_DIR)
    count = await _ingest_docs(backend, model, documents)
    total = await backend.count()
    print(f"Local: {count} chunks from {len(documents)} docs — backend total: {total}")
    return count


async def ingest_confluence():
    from sources.confluence import fetch_pages
    backend = get_search_backend()
    model = _model_or_none()
    documents = fetch_pages()
    count = await _ingest_docs(backend, model, documents)
    print(f"Confluence: {count} chunks from {len(documents)} pages")
    return count


async def ingest_jira():
    from sources.jira_source import fetch_tickets
    backend = get_search_backend()
    model = _model_or_none()
    documents = fetch_tickets()
    count = await _ingest_docs(backend, model, documents)
    print(f"Jira: {count} chunks from {len(documents)} tickets")
    return count


async def main():
    import argparse
    from backends import initialize

    parser = argparse.ArgumentParser(description="Askable ingestion pipeline")
    parser.add_argument("--source", choices=["local", "confluence", "jira"], default="local")
    args = parser.parse_args()

    print("=== Document Indexing Pipeline ===\n")
    await initialize()   # boot ES + embedding model (same as the server does)

    if args.source == "confluence":
        await ingest_confluence()
    elif args.source == "jira":
        await ingest_jira()
    else:
        total = await ingest_local()
        print(f"\n=== Indexing complete: {total} chunks ===")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
