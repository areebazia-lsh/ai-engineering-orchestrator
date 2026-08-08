"""
CLI: Ingest a repository into the vector knowledge base.

Usage (from backend/ directory, with ai-orchestrator env active):

    python scripts/ingest_repo.py \\
        --path  e:/DevEps/ai-engineering-orchestrator/backend \\
        --name  "AI Engineering Orchestrator" \\
        [--project-id  <existing-uuid>]   # omit to auto-create a project
        [--clear]                          # delete existing vectors first
        [--dry-run]                        # parse only, no DB writes

Examples:
    # Ingest the backend itself (creates a new project automatically)
    python scripts/ingest_repo.py --path . --name "AI Orchestrator Backend"

    # Re-ingest with fresh vectors
    python scripts/ingest_repo.py --path . --name "AI Orchestrator Backend" --clear

    # Check what would be parsed without writing anything
    python scripts/ingest_repo.py --path . --name "test" --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Ensure project root is on path regardless of where the script is called from
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Silence the fastembed HuggingFace symlink warning on Windows
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Ingest a repository into the AI Engineering Orchestrator knowledge base",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--path", "-p",
        required=True,
        help="Path to the repository root to ingest",
    )
    p.add_argument(
        "--name", "-n",
        required=True,
        help="Human-readable project name",
    )
    p.add_argument(
        "--project-id",
        default=None,
        help="Existing project UUID (creates a new project if omitted)",
    )
    p.add_argument(
        "--clear",
        action="store_true",
        default=False,
        help="Delete existing vectors for this project before ingesting",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Parse and chunk files but do not write to the database",
    )
    return p.parse_args()


def _progress(msg: str) -> None:
    print(f"  {msg}", flush=True)


def main() -> None:
    args = parse_args()

    repo_path = os.path.abspath(args.path)
    if not os.path.isdir(repo_path):
        print(f"ERROR: path does not exist or is not a directory: {repo_path}")
        sys.exit(1)

    print("=" * 60)
    print("AI Engineering Orchestrator — Repository Ingestion")
    print("=" * 60)
    print(f"  Repository : {repo_path}")
    print(f"  Name       : {args.name}")
    print(f"  Clear      : {args.clear}")
    print(f"  Dry-run    : {args.dry_run}")

    # ── Load config ──────────────────────────────────────────────────────────
    print("\n[1/5] Loading configuration...")
    from app.core.config import settings
    print(f"  Supabase URL : {settings.SUPABASE_URL[:45]}...")

    # ── Init Supabase ────────────────────────────────────────────────────────
    print("\n[2/5] Connecting to Supabase...")
    from app.database.supabase_client import init_supabase_client
    client = init_supabase_client()
    print("  Connected OK")

    # ── Resolve / create project ─────────────────────────────────────────────
    print("\n[3/5] Resolving project record...")
    from app.services.project_service import ProjectService
    svc = ProjectService(client)

    project_id = args.project_id
    if project_id:
        project = svc.get_project(project_id)
        if not project:
            print(f"  ERROR: project_id '{project_id}' not found in database.")
            sys.exit(1)
        print(f"  Using existing project: {project['name']} ({project_id})")
    else:
        project = svc.create_project(
            name=args.name,
            description=f"Repository at {repo_path}",
        )
        project_id = project["id"]
        print(f"  Created project: {args.name} ({project_id})")

    if args.dry_run:
        print("\n[DRY RUN] Parsing files only — no DB writes.\n")
        _dry_run(repo_path, project_id, args.name)
        return

    # ── Init vector store ────────────────────────────────────────────────────
    print("\n[4/5] Initialising vector store...")
    from app.knowledge.vector_store.supabase_store import SupabaseVectorStore
    vector_store = SupabaseVectorStore(client)
    print("  Vector store ready")

    # ── Run ingestion ────────────────────────────────────────────────────────
    print("\n[5/5] Running ingestion pipeline...\n")
    from app.ingestion.pipeline import ingest_repository
    from app.services.project_service import ProjectService as PS

    svc.update_ingestion_status(project_id, "running")
    t0 = time.time()

    try:
        result = ingest_repository(
            repo_path=repo_path,
            project_id=project_id,
            project_name=args.name,
            vector_store=vector_store,
            clear_existing=args.clear,
            progress_cb=_progress,
        )
        svc.update_ingestion_status(project_id, "done")
    except Exception as exc:
        svc.update_ingestion_status(project_id, "failed")
        print(f"\nFATAL ERROR during ingestion: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    elapsed = time.time() - t0

    print("\n" + "=" * 60)
    print("INGESTION COMPLETE")
    print("=" * 60)
    print(f"  Project ID        : {result.project_id}")
    print(f"  Files processed   : {result.files_processed}")
    print(f"  Files skipped     : {result.files_skipped}")
    print(f"  Chunks created    : {result.chunks_created}")
    print(f"  Vectors upserted  : {result.vectors_upserted}")
    print(f"  Errors            : {len(result.errors)}")
    print(f"  Duration          : {elapsed:.1f}s")

    if result.errors:
        print("\nErrors encountered (non-fatal):")
        for e in result.errors[:10]:
            print(f"  - {e}")

    # Show stats from DB
    print("\nVector store stats for this project:")
    stats = vector_store.get_stats(project_id=project_id)
    for col, count in stats.items():
        print(f"  {col:<30} : {count}")
    print(f"  {'TOTAL':<30} : {sum(stats.values())}")

    print(f"\nProject ID to use in chat requests: {project_id}")
    print("Done.\n")


def _dry_run(repo_path: str, project_id: str, project_name: str) -> None:
    """Parse and chunk without writing to the DB."""
    from app.ingestion.parsers.python_parser import PythonParser
    from app.ingestion.chunkers.code_chunker import CodeChunker
    from app.ingestion.pipeline import _collect_files, SKIP_FILES, MAX_FILE_SIZE_BYTES
    from pathlib import Path

    root = Path(repo_path)
    parser  = PythonParser()
    chunker = CodeChunker(project_id=project_id, project_name=project_name)

    py_files = _collect_files(root, {".py"})
    md_files = _collect_files(root, {".md", ".rst", ".txt"})

    total_chunks = 0
    for f in py_files:
        if f.name in SKIP_FILES or f.stat().st_size > MAX_FILE_SIZE_BYTES:
            continue
        parsed = parser.parse_file(f)
        chunks = []
        for pc in parsed:
            chunks.extend(chunker.chunk(pc))
        total_chunks += len(chunks)
        print(f"  {str(f.relative_to(root)):<55} → {len(chunks)} chunks")

    print(f"\nTotal Python chunks  : {total_chunks}")
    print(f"Total Python files   : {len(py_files)}")
    print(f"Total doc files      : {len(md_files)}")
    print("\nDry run complete — nothing written to database.")


if __name__ == "__main__":
    main()
