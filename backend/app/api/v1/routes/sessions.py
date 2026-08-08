"""
Sessions endpoints.

POST   /api/v1/sessions
GET    /api/v1/sessions/{session_id}
GET    /api/v1/sessions/{session_id}/messages
GET    /api/v1/projects/{project_id}/sessions
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.api.v1.schemas import SessionCreateRequest, SessionResponse, MessageResponse
from app.database.supabase_client import get_supabase_client
from app.services.session_service import SessionService, MessageService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def create_session(body: SessionCreateRequest) -> SessionResponse:
    client = get_supabase_client()
    service = SessionService(client)
    session = service.create_session(
        project_id=body.project_id,
        title=body.title,
    )
    return SessionResponse(**session)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    client = get_supabase_client()
    service = SessionService(client)
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse(**session)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
async def get_messages(session_id: str) -> list[MessageResponse]:
    client = get_supabase_client()
    msg_service = MessageService(client)
    messages = msg_service.get_messages(session_id, limit=200)
    return [MessageResponse(**m) for m in messages]


@router.get("/projects/{project_id}/sessions", response_model=list[SessionResponse])
async def list_sessions(project_id: str) -> list[SessionResponse]:
    client = get_supabase_client()
    service = SessionService(client)
    sessions = service.list_sessions(project_id)
    return [SessionResponse(**s) for s in sessions]
