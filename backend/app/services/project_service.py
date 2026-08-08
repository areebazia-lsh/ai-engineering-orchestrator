"""
Project domain service.
Handles all database operations for the `projects` table.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from datetime import datetime, timezone

from supabase import Client

from app.database.base_service import BaseService

logger = logging.getLogger(__name__)


class ProjectService(BaseService):

    TABLE = "projects"

    def __init__(self, client: Client) -> None:
        super().__init__(client, self.TABLE)

    def create_project(
        self,
        name: str,
        description: Optional[str] = None,
        repository_url: Optional[str] = None,
        primary_language: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new project record."""
        data = {
            "name": name,
            "description": description,
            "repository_url": repository_url,
            "primary_language": primary_language,
            "ingestion_status": "pending",
        }
        # Remove None values so Supabase uses column defaults
        data = {k: v for k, v in data.items() if v is not None}
        project = self.create(data)
        logger.info(f"Project created: id={project['id']} name={name!r}")
        return project

    def get_project(self, project_id: str) -> Optional[dict[str, Any]]:
        return self.get_by_id(project_id)

    def list_projects(self) -> list[dict[str, Any]]:
        return self.list_all(order_by="created_at", ascending=False)

    def update_ingestion_status(
        self, project_id: str, status: str
    ) -> dict[str, Any]:
        """Called by ingestion pipeline to track progress."""
        data: dict[str, Any] = {
            "ingestion_status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if status == "done":
            data["ingested_at"] = datetime.now(timezone.utc).isoformat()
        return self.update(project_id, data)
