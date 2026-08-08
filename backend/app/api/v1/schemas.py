"""
API request and response schemas (Pydantic models).

All HTTP payloads are validated and serialised through these models.
This provides type safety, automatic validation, and OpenAPI documentation.

Naming convention:
  - *Request: incoming request body
  - *Response: outgoing response body
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Chat ───────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """POST /api/v1/chat request body."""
    message: str = Field(..., min_length=1, max_length=10000, description="User message")
    project_id: Optional[str] = Field(None, description="Optional project UUID")
    session_id: Optional[str] = Field(None, description="Existing session UUID (creates new if omitted)")
    agent_mode: Optional[str] = Field("auto", description="Agent mode: 'auto' for full workflow, or specific agent name")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Explain the authentication module in my project",
                "project_id": "123e4567-e89b-12d3-a456-426614174000",
                "session_id": "789e4567-e89b-12d3-a456-426614174000",
            }
        }


class AgentStepResponse(BaseModel):
    """Single agent execution step in the trace."""
    agent: str
    input_summary: str
    output_summary: str
    tokens_used: int


class ChatResponse(BaseModel):
    """POST /api/v1/chat response body."""
    session_id: str
    intent: Optional[str]
    workflow: Optional[str]
    plan: list[dict[str, Any]]
    response: str
    response_type: str
    total_tokens: int
    duration_ms: int
    agent_steps: list[AgentStepResponse]
    error: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "789e4567-e89b-12d3-a456-426614174000",
                "intent": "explain authentication architecture",
                "workflow": "code_explanation",
                "plan": [
                    {"step": 1, "type": "respond", "description": "Provide explanation"}
                ],
                "response": "The authentication module uses JWT tokens...",
                "response_type": "text",
                "total_tokens": 523,
                "duration_ms": 2340,
                "agent_steps": [
                    {
                        "agent": "router",
                        "input_summary": "message: Explain the authentication module...",
                        "output_summary": "intent='explain authentication architecture' workflow=code_explanation",
                        "tokens_used": 89,
                    }
                ],
                "error": None,
            }
        }


# ── Project ────────────────────────────────────────────────────────────────────

class ProjectCreateRequest(BaseModel):
    """POST /api/v1/projects request body."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    repository_url: Optional[str] = Field(None, max_length=500)
    primary_language: Optional[str] = Field(None, max_length=50)


class ProjectResponse(BaseModel):
    """Project representation."""
    id: str
    name: str
    description: Optional[str]
    repository_url: Optional[str]
    repository_path: Optional[str]
    primary_language: Optional[str]
    ingestion_status: str
    ingested_at: Optional[str]
    created_at: str
    updated_at: str


# ── Session ────────────────────────────────────────────────────────────────────

class SessionCreateRequest(BaseModel):
    """POST /api/v1/sessions request body."""
    project_id: str
    title: Optional[str] = Field(None, max_length=255)


class SessionResponse(BaseModel):
    """Session representation."""
    id: str
    project_id: str
    title: Optional[str]
    status: str
    created_at: str
    updated_at: str


# ── Message ────────────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    """Message representation."""
    id: str
    session_id: str
    role: str
    content: str
    metadata: dict[str, Any]
    created_at: str


# ── Error ──────────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    """Standard error response for 4xx/5xx."""
    detail: str
    error_code: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "detail": "Session not found",
                "error_code": "SESSION_NOT_FOUND",
            }
        }
