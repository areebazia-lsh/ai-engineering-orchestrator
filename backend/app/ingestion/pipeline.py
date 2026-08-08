"""
Repository ingestion pipeline.

Orchestrates: file discovery → parsing → chunking → embedding → vector store upsert.

Flow:
    ingest_repository(path, project_id)
        → walk all .py / .md files
        → PythonParser  → list[ParsedChunk]
        → CodeChunker   → list[EmbeddableChunk]
        → embedder.embed_texts()  (batch, no LLM)
        → SupabaseVectorStore.upsert_batch()

Design decisions:
  - Embeddings are generated in a single batched call per file batch (EMBED_BATCH).
    This avoids loading the ONNX model repeatedly and saturates the CPU efficiently.
  - We upsert, never insert-only, so re-running on an already-ingested repo
    updates changed chunks without creating duplicates.
  - The function is synchronous (called from the async CLI/API via run_in_executor
    or asyncio.to_thread) because the ONNX model is synchronous.
  - Progress is reported via a callback so both CLI and API can display it.
  - Files that fail to parse are logged and skipped — never crash the whole job.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from app.ingestion.parsers.python_ast_parser import PythonASTParser
from app.ingestion.parsers.markdown_parser import MarkdownParser, DocChunk
from app.ingestion.chunkers.code_chunker import CodeChunker, EmbeddableChunk
from app.ingestion.embedder import embed_texts
from app.knowledge.vector_store.supabase_store import (
    SupabaseVectorStore,
    COLLECTION_CODE,
    COLLECTION_DOCS,
)

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
EMBED_BATCH         = 32     # chunks per embedding call
DB_UPSERT_BATCH     = 50     # records per Supabase upsert call
MAX_FILE_SIZE_BYTES = 200_000  # skip files larger than 200 KB

# Files / dirs to always skip
SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
}
SKIP_FILES = {"__init__.py"}   # skip empty init files


@dataclass
class IngestionResult:
    """Summary returned after a completed ingestion run."""
    project_id:       str
    repo_path:        str
    files_processed:  int = 0
    chunks_created:   int = 0
    vectors_upserted: int = 0
    files_skipped:    int = 0
    errors:           list[str] = field(default_factory=list)


# ── Main entry point ───────────────────────────────────────────────────────────

def ingest_repository(
    repo_path:    str | Path,
    project_id:   str,
    project_name: str,
    vector_store: SupabaseVectorStore,
    *,
    progress_cb: Optional[Callable[[str], None]] = None,
    clear_existing: bool = False,
) -> IngestionResult:
    """
    Parse, chunk, embed, and store all code and documentation in a repository.

    Args:
        repo_path:      Absolute path to the root of the repository.
        project_id:     UUID of the project record in Supabase.
        project_name:   Human-readable name for metadata.
        vector_store:   Initialised SupabaseVectorStore instance.
        progress_cb:    Optional callback(message) for progress reporting.
        clear_existing: If True, delete all existing vectors for this project first.

    Returns:
        IngestionResult with counts and any errors.
    """
    repo = Path(repo_path).resolve()
    result = IngestionResult(project_id=project_id, repo_path=str(repo))

    def log(msg: str) -> None:
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    log(f"Ingestion start | project={project_name} path={repo}")

    if clear_existing:
        deleted = vector_store.delete_project(project_id)
        log(f"Cleared {deleted} existing vectors for project {project_id}")

    # ── Initialise parsers and chunker ────────────────────────────────────────
    py_parser   = PythonASTParser()
    md_parser   = MarkdownParser()
    py_chunker  = CodeChunker(project_id=project_id, project_name=project_name, language="python")

    # ── Collect files ─────────────────────────────────────────────────────────
    py_files = _collect_files(repo, extensions={".py"})
    md_files = _collect_files(repo, extensions={".md", ".rst", ".txt"})
    log(f"Found {len(py_files)} Python files, {len(md_files)} doc files")

    # ── Process Python files ──────────────────────────────────────────────────
    code_chunks: list[EmbeddableChunk] = []
    for fpath in py_files:
        rel = str(fpath.relative_to(repo))
        if fpath.name in SKIP_FILES:
            result.files_skipped += 1
            continue
        if fpath.stat().st_size > MAX_FILE_SIZE_BYTES:
            log(f"  SKIP (too large): {rel}")
            result.files_skipped += 1
            continue
        try:
            parsed = py_parser.parse_file(fpath)
            if not parsed:
                result.files_skipped += 1
                continue
            for pc in parsed:
                # Use relative path for portability
                pc.file_path = rel
                code_chunks.extend(py_chunker.chunk(pc))
            result.files_processed += 1
        except Exception as exc:
            msg = f"Error parsing {rel}: {exc}"
            logger.warning(msg)
            result.errors.append(msg)

    log(f"Parsed Python: {result.files_processed} files → {len(code_chunks)} code chunks")

    # ── Process documentation files ───────────────────────────────────────────
    doc_embeddable: list[dict] = []
    for fpath in md_files:
        rel = str(fpath.relative_to(repo))
        if fpath.stat().st_size > MAX_FILE_SIZE_BYTES:
            result.files_skipped += 1
            continue
        try:
            doc_type = _infer_doc_type(fpath)
            doc_chunks = md_parser.parse_file(fpath, doc_type=doc_type)
            for dc in doc_chunks:
                dc.file_path = rel
                doc_embeddable.append(_doc_chunk_to_embeddable(dc, project_id, project_name))
            result.files_processed += 1
        except Exception as exc:
            msg = f"Error parsing doc {rel}: {exc}"
            logger.warning(msg)
            result.errors.append(msg)

    log(f"Parsed docs: {len(doc_embeddable)} doc chunks from {len(md_files)} files")

    # ── Embed and upsert code chunks ──────────────────────────────────────────
    if code_chunks:
        upserted = _embed_and_upsert(
            chunks=code_chunks,
            collection=COLLECTION_CODE,
            vector_store=vector_store,
            log=log,
        )
        result.vectors_upserted += upserted
        result.chunks_created   += len(code_chunks)

    # ── Embed and upsert doc chunks ───────────────────────────────────────────
    if doc_embeddable:
        upserted = _embed_and_upsert_raw(
            raw_records=doc_embeddable,
            collection=COLLECTION_DOCS,
            vector_store=vector_store,
            log=log,
        )
        result.vectors_upserted += upserted
        result.chunks_created   += len(doc_embeddable)

    log(
        f"Ingestion complete | "
        f"files={result.files_processed} "
        f"chunks={result.chunks_created} "
        f"vectors={result.vectors_upserted} "
        f"errors={len(result.errors)}"
    )
    return result


# ── Internal helpers ───────────────────────────────────────────────────────────

def _collect_files(root: Path, extensions: set[str]) -> list[Path]:
    """Walk a directory tree and return all files with given extensions."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip directories in-place so os.walk doesn't descend into them
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            p = Path(dirpath) / fname
            if p.suffix.lower() in extensions:
                files.append(p)
    return sorted(files)


def _infer_doc_type(path: Path) -> str:
    name = path.name.lower()
    if "readme" in name:
        return "readme"
    if "architect" in name or "design" in name:
        return "architecture"
    if "api" in name:
        return "api_doc"
    if "require" in name or "spec" in name:
        return "requirement"
    return "markdown"


def _doc_chunk_to_embeddable(dc: DocChunk, project_id: str, project_name: str) -> dict:
    embed_text = f"Documentation [{dc.doc_type}] section: {dc.section}\nfile: {dc.file_path}\n\n{dc.content}"
    chunk_id = f"{dc.file_path}:doc:{dc.section}:{dc.start_line}"
    return {
        "collection":  COLLECTION_DOCS,
        "chunk_id":    chunk_id,
        "project_id":  project_id,
        "content":     dc.content,
        "embed_text":  embed_text,
        "metadata": {
            "project_id":    project_id,
            "project_name":  project_name,
            "file_path":     dc.file_path,
            "doc_type":      dc.doc_type,
            "section":       dc.section,
            "start_line":    dc.start_line,
            "end_line":      dc.end_line,
            "chunk_id":      chunk_id,
        },
    }


def _embed_and_upsert(
    chunks:       list[EmbeddableChunk],
    collection:   str,
    vector_store: SupabaseVectorStore,
    log:          Callable[[str], None],
) -> int:
    """Batch-embed EmbeddableChunks and upsert into vector store."""
    total_upserted = 0
    texts = [c.embed_text for c in chunks]

    for batch_start in range(0, len(chunks), EMBED_BATCH):
        batch_chunks = chunks[batch_start: batch_start + EMBED_BATCH]
        batch_texts  = texts[batch_start: batch_start + EMBED_BATCH]

        try:
            embeddings = embed_texts(batch_texts)
        except Exception as exc:
            log(f"  Embedding failed for batch {batch_start}: {exc}")
            continue

        records = [
            {
                "collection":  collection,
                "chunk_id":    c.chunk_id,
                "project_id":  c.metadata["project_id"],
                "content":     c.raw_content,
                "embed_text":  c.embed_text,
                "embedding":   emb,
                "metadata":    c.metadata,
            }
            for c, emb in zip(batch_chunks, embeddings)
        ]
        # Upsert in DB batches
        for db_start in range(0, len(records), DB_UPSERT_BATCH):
            db_batch = records[db_start: db_start + DB_UPSERT_BATCH]
            try:
                n = vector_store.upsert_batch(db_batch)
                total_upserted += n
            except Exception as exc:
                log(f"  DB upsert failed: {exc}")

        log(f"  [{collection}] {batch_start + len(batch_chunks)}/{len(chunks)} chunks embedded & stored")

    return total_upserted


def _embed_and_upsert_raw(
    raw_records:  list[dict],
    collection:   str,
    vector_store: SupabaseVectorStore,
    log:          Callable[[str], None],
) -> int:
    """Same as _embed_and_upsert but for pre-built raw record dicts."""
    total = 0
    texts = [r["embed_text"] for r in raw_records]

    for i in range(0, len(raw_records), EMBED_BATCH):
        batch_recs  = raw_records[i: i + EMBED_BATCH]
        batch_texts = texts[i: i + EMBED_BATCH]
        try:
            embeddings = embed_texts(batch_texts)
        except Exception as exc:
            log(f"  Embedding failed for doc batch {i}: {exc}")
            continue

        records = [
            {**r, "embedding": emb}
            for r, emb in zip(batch_recs, embeddings)
        ]
        for db_start in range(0, len(records), DB_UPSERT_BATCH):
            db_batch = records[db_start: db_start + DB_UPSERT_BATCH]
            try:
                n = vector_store.upsert_batch(db_batch)
                total += n
            except Exception as exc:
                log(f"  DB upsert failed: {exc}")

        log(f"  [{collection}] {i + len(batch_recs)}/{len(raw_records)} doc chunks stored")

    return total
