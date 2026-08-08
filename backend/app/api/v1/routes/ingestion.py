"""
Repository ingestion endpoints.

POST /api/v1/projects/{project_id}/ingest
    Trigger ingestion of a local repository path.
    Runs the pipeline in a background thread (asyncio.to_thread) so the
    HTTP response returns immediately with a job_id.
    Actual progress is polled via:

GET  /api/v1/projects/{project_id}/ingest/status
    Returns current ingestion_status from the projects table.

GET  /api/v1/projects/{project_id}/knowledge/stats
    Returns chunk counts per collection from the vector store.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.database.supabase_client import get_supabase_client
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response schemas ─────────────────────────────────────────────────

class IngestRequest(BaseModel):
    repository_paths: list[str] = Field(
        ...,
        description="List of absolute paths to repositories on the server filesystem",
    )
    clear_existing: bool = Field(
        False,
        description="If true, delete existing vectors before re-ingesting",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "repository_paths": [
                    "e:/DevEps/ai-engineering-orchestrator/backend",
                    "e:/DevEps/ai-engineering-orchestrator/frontend"
                ],
                "clear_existing": False,
            }
        }


class IngestResponse(BaseModel):
    project_id: str
    status:     str
    message:    str


class IngestStatusResponse(BaseModel):
    project_id:       str
    ingestion_status: str
    ingested_at:      Any


class KnowledgeStatsResponse(BaseModel):
    project_id:              str
    code_knowledge:          int
    documentation_knowledge: int
    bug_knowledge:           int
    project_knowledge:       int
    total:                   int


# ── Background ingestion task ──────────────────────────────────────────────────

def _run_ingestion_sync(
    project_id:      str,
    project_name:    str,
    repo_paths:      list[str],
    clear_existing:  bool,
    vector_store,
) -> None:
    """
    Synchronous ingestion — runs in asyncio.to_thread so it doesn't block
    the event loop.  Updates project ingestion_status in Supabase.
    """
    from app.ingestion.pipeline import ingest_repository
    from app.database.supabase_client import get_supabase_client
    from app.services.project_service import ProjectService

    client = get_supabase_client()
    svc    = ProjectService(client)

    try:
        svc.update_ingestion_status(project_id, "running")
        
        # Process each path
        for repo_path in repo_paths:
            logger.info(f"Starting ingestion for path: {repo_path}")
            result = ingest_repository(
                repo_path=repo_path,
                project_id=project_id,
                project_name=project_name,
                vector_store=vector_store,
                clear_existing=clear_existing,
                progress_cb=lambda msg: logger.info(f"[ingest:{project_id}] {msg}"),
            )
            clear_existing = False  # Only clear on first path
        
        svc.update_ingestion_status(project_id, "done")
        logger.info(
            f"Ingestion finished | project={project_id} paths={len(repo_paths)}"
        )
    except Exception as exc:
        logger.exception(f"Ingestion failed | project={project_id}: {exc}")
        svc.update_ingestion_status(project_id, "failed")


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/ingest",
    response_model=IngestResponse,
    status_code=202,
)
async def start_ingestion(
    project_id: str,
    body:       IngestRequest,
    request:    Request,
) -> IngestResponse:
    """
    Start repository ingestion in the background.
    Returns 202 Accepted immediately; poll /ingest/status for progress.
    """
    client = get_supabase_client()
    svc    = ProjectService(client)

    project = svc.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    vector_store = getattr(request.app.state, "vector_store", None)
    if vector_store is None:
        raise HTTPException(
            status_code=503,
            detail="Vector store not initialised — check server startup logs",
        )

    project_name = project.get("name", "unknown")
    
    # Process all provided paths
    paths_to_ingest = body.repository_paths
    if isinstance(paths_to_ingest, str):
        paths_to_ingest = [paths_to_ingest]

    # Fire and forget — result tracked via DB status field
    asyncio.create_task(
        asyncio.to_thread(
            _run_ingestion_sync,
            project_id,
            project_name,
            paths_to_ingest,
            body.clear_existing,
            vector_store,
        )
    )

    logger.info(
        f"Ingestion started (async) | project={project_id} paths={paths_to_ingest}"
    )
    return IngestResponse(
        project_id=project_id,
        status="running",
        message=f"Ingestion started for '{project_name}'. Poll /ingest/status for progress.",
    )


@router.get(
    "/projects/{project_id}/ingest/status",
    response_model=IngestStatusResponse,
)
async def get_ingestion_status(project_id: str) -> IngestStatusResponse:
    client  = get_supabase_client()
    svc     = ProjectService(client)
    project = svc.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return IngestStatusResponse(
        project_id=project_id,
        ingestion_status=project.get("ingestion_status", "unknown"),
        ingested_at=project.get("ingested_at"),
    )


@router.get(
    "/projects/{project_id}/knowledge/stats",
    response_model=KnowledgeStatsResponse,
)
async def get_knowledge_stats(project_id: str, request: Request) -> KnowledgeStatsResponse:
    vector_store = getattr(request.app.state, "vector_store", None)
    if vector_store is None:
        raise HTTPException(status_code=503, detail="Vector store not initialised")

    stats = vector_store.get_stats(project_id=project_id)
    return KnowledgeStatsResponse(
        project_id=project_id,
        code_knowledge=stats.get("code_knowledge", 0),
        documentation_knowledge=stats.get("documentation_knowledge", 0),
        bug_knowledge=stats.get("bug_knowledge", 0),
        project_knowledge=stats.get("project_knowledge", 0),
        total=sum(stats.values()),
    )


class DeleteFileRequest(BaseModel):
    file_path: str = Field(..., description="Path of the file to delete")


@router.delete(
    "/projects/{project_id}/files",
    status_code=200,
)
async def delete_file(
    project_id: str,
    body: DeleteFileRequest,
    request: Request,
) -> dict[str, str]:
    """Delete a specific file and its vectors from the project."""
    vector_store = getattr(request.app.state, "vector_store", None)
    if vector_store is None:
        raise HTTPException(status_code=503, detail="Vector store not initialised")

    count = vector_store.delete_file(project_id, body.file_path)
    
    logger.info(
        f"Deleted {count} vectors for file {body.file_path} from project {project_id}"
    )
    return {
        "status": "success",
        "message": f"Deleted {count} vectors for file '{body.file_path}'",
    }


@router.get(
    "/projects/{project_id}/knowledge/files",
    response_model=list[dict[str, Any]],
)
async def get_project_files(project_id: str, request: Request) -> list[dict[str, Any]]:
    """List all files that have been ingested for this project."""
    vector_store = getattr(request.app.state, "vector_store", None)
    if vector_store is None:
        raise HTTPException(status_code=503, detail="Vector store not initialised")

    # Get unique source files from vectors
    from app.orchestration.state import GraphState
    result = (
        vector_store._client.table(vector_store.TABLE)
        .select("metadata->>source", count="exact")
        .eq("project_id", project_id)
        .is_("metadata->>source", "not.is.null")
        .execute()
    )
    
    files = []
    if result.data:
        from collections import Counter
        sources = [item.get("metadata", {}).get("source", "") for item in result.data]
        file_counts = Counter(sources)
        
        for source, count in file_counts.items():
            files.append({
                "path": source,
                "chunk_count": count,
            })
    
    return files
