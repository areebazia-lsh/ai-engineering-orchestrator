"""
Session domain service.
Handles sessions (conversation threads) and their messages.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from datetime import datetime, timezone

from supabase import Client

from app.database.base_service import BaseService

logger = logging.getLogger(__name__)


class SessionService(BaseService):

    TABLE = "sessions"

    def __init__(self, client: Client) -> None:
        super().__init__(client, self.TABLE)

    def create_session(
        self,
        project_id: str,
        title: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new session tied to a project."""
        data = {
            "project_id": project_id,
            "title": title or "New Session",
            "status": "active",
        }
        session = self.create(data)
        logger.info(f"Session created: id={session['id']} project={project_id}")
        return session

    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        return self.get_by_id(session_id)

    def list_sessions(self, project_id: str) -> list[dict[str, Any]]:
        """List all sessions for a project."""
        return self.list_all(
            filters={"project_id": project_id},
            order_by="updated_at",
            ascending=False,
        )

    def update_session_title(
        self, session_id: str, title: str
    ) -> dict[str, Any]:
        return self.update(session_id, {"title": title, "updated_at": datetime.now(timezone.utc).isoformat()})

    def archive_session(self, session_id: str) -> dict[str, Any]:
        return self.update(
            session_id,
            {"status": "archived", "updated_at": datetime.now(timezone.utc).isoformat()},
        )


# ── Message operations ─────────────────────────────────────────────────────────
# Messages are semantically part of sessions, so we keep them in the same service.


class MessageService(BaseService):

    TABLE = "messages"

    def __init__(self, client: Client) -> None:
        super().__init__(client, self.TABLE)

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Add a message to a session.
        role: "user" | "assistant" | "system" | "tool"
        """
        data = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "metadata": metadata or {},
        }
        message = self.create(data)
        logger.debug(f"Message added: session={session_id} role={role}")
        return message

    def get_messages(
        self, session_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Retrieve conversation history for a session, oldest first."""
        return self.list_all(
            filters={"session_id": session_id},
            order_by="created_at",
            ascending=True,
            limit=limit,
        )
