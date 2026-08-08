"""
Agent trace service.
Persists full agent execution traces for observability.
Each request through the graph produces one trace record with all steps.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from supabase import Client

from app.database.base_service import BaseService

logger = logging.getLogger(__name__)


class TraceService(BaseService):

    TABLE = "agent_traces"

    def __init__(self, client: Client) -> None:
        super().__init__(client, self.TABLE)

    def save_trace(
        self,
        session_id: str,
        message_id: Optional[str],
        workflow: str,
        steps: list[dict[str, Any]],
        total_tokens: int = 0,
        duration_ms: int = 0,
    ) -> dict[str, Any]:
        """
        Save a complete agent execution trace.

        Args:
            session_id:   The session this trace belongs to.
            message_id:   The assistant message that was generated (nullable).
            workflow:     Workflow name e.g. "code_debugging", "explain_code".
            steps:        List of step dicts: {agent, input_summary, output_summary, tokens}.
            total_tokens: Sum of all LLM tokens used in this turn.
            duration_ms:  Wall-clock time for the full graph execution.
        """
        data = {
            "session_id": session_id,
            "message_id": message_id,
            "workflow": workflow,
            "steps": steps,
            "total_tokens": total_tokens,
            "duration_ms": duration_ms,
        }
        trace = self.create(data)
        logger.debug(
            f"Trace saved: id={trace['id']} workflow={workflow} "
            f"steps={len(steps)} tokens={total_tokens} duration={duration_ms}ms"
        )
        return trace

    def get_session_traces(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve all traces for a session (most recent first)."""
        return self.list_all(
            filters={"session_id": session_id},
            order_by="created_at",
            ascending=False,
        )
