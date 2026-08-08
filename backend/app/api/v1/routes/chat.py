"""
Chat endpoint.

POST /api/v1/chat
  - Creates or uses an existing session
  - Runs the full LangGraph agent workflow
  - Returns the agent response + trace metadata

This is the primary user-facing endpoint in Phase 1.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.v1.schemas import ChatRequest, ChatResponse
from app.database.supabase_client import get_supabase_client
from app.services.session_service import SessionService
from app.services.project_service import ProjectService
from app.orchestration.runner import run_graph

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Dependencies ───────────────────────────────────────────────────────────────

def get_compiled_graph(request: Request):
    """Retrieve the compiled LangGraph from app.state (set during lifespan)."""
    return request.app.state.compiled_graph

def get_orchestration_nodes(request: Request):
    """Retrieve the orchestration nodes dict from app.state (set during lifespan)."""
    return request.app.state.orchestration_nodes


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse, status_code=200)
async def chat(
    body: ChatRequest,
    compiled_graph = Depends(get_compiled_graph),
    nodes = Depends(get_orchestration_nodes),
) -> ChatResponse:
    """
    Send a message to the AI agent and receive a response.

    Workflow:
      1. Validate or create session (and project if needed).
      2. Invoke the LangGraph workflow via run_graph().
      3. Return the response with full trace.

    Error handling:
      - 400: Invalid input (Pydantic catches this automatically)
      - 404: Session or project not found
      - 500: Graph execution failure (rare — most agent errors are handled gracefully)
    """
    client = get_supabase_client()
    session_service = SessionService(client)
    project_service = ProjectService(client)

    user_message = body.message
    session_id = body.session_id
    project_id = body.project_id

    # ── Session/Project resolution ─────────────────────────────────────────────
    # Case 1: session_id provided → use it, fetch project_id from DB
    # Case 2: project_id provided → create new session
    # Case 3: neither provided → create a default project and session

    if session_id:
        # Existing session
        session = session_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        project_id = session["project_id"]
        logger.info(f"Using existing session | session_id={session_id} project_id={project_id}")

    else:
        # New session
        if not project_id:
            # Create a default project for the user (Phase 2: tie to authenticated user)
            project = project_service.create_project(
                name="Default Project",
                description="Automatically created project",
            )
            project_id = project["id"]
            logger.info(f"Created default project | project_id={project_id}")
        else:
            # Validate that project exists
            project = project_service.get_project(project_id)
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")

        # Create session
        session = session_service.create_session(
            project_id=project_id,
            title="New Session",
        )
        session_id = session["id"]
        logger.info(f"Created new session | session_id={session_id} project_id={project_id}")

    # ── Run the graph ──────────────────────────────────────────────────────────
    try:
        result = await run_graph(
            compiled_graph=compiled_graph,
            orchestration_nodes=nodes,
            session_id=session_id,
            project_id=project_id,
            user_message=user_message,
            agent_mode=body.agent_mode or "auto",
        )
    except Exception as exc:
        logger.exception("Graph execution failed unexpectedly")
        raise HTTPException(
            status_code=500,
            detail=f"Graph execution error: {exc}",
        ) from exc

    # ── Build response ─────────────────────────────────────────────────────────
    return ChatResponse(
        session_id=result.session_id,
        intent=result.intent,
        workflow=result.workflow,
        plan=result.plan,
        response=result.response,
        response_type=result.response_type,
        total_tokens=result.total_tokens,
        duration_ms=result.duration_ms,
        agent_steps=result.agent_steps,
        error=result.error,
    )


@router.get("/health", status_code=200)
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}
