"""
Projects endpoints.

GET    /api/v1/projects
POST   /api/v1/projects
GET    /api/v1/projects/{project_id}
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.api.v1.schemas import ProjectCreateRequest, ProjectResponse
from app.database.supabase_client import get_supabase_client
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects() -> list[ProjectResponse]:
    client = get_supabase_client()
    service = ProjectService(client)
    projects = service.list_projects()
    return [ProjectResponse(**p) for p in projects]


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(body: ProjectCreateRequest) -> ProjectResponse:
    client = get_supabase_client()
    service = ProjectService(client)
    project = service.create_project(
        name=body.name,
        description=body.description,
        repository_url=body.repository_url,
        primary_language=body.primary_language,
    )
    return ProjectResponse(**project)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str) -> ProjectResponse:
    client = get_supabase_client()
    service = ProjectService(client)
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse(**project)
