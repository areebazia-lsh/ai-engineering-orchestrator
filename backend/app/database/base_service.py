"""
Base database service.

Provides common CRUD helpers that all domain services inherit.
Keeps Supabase query patterns in one place — if we ever swap the DB layer,
only this file needs to change.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from supabase import Client

logger = logging.getLogger(__name__)


class BaseService:
    """
    Thin wrapper around the Supabase PostgREST client.
    All domain services (ProjectService, SessionService, etc.) extend this.
    """

    def __init__(self, client: Client, table: str) -> None:
        self._client = client
        self._table = table

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_by_id(self, record_id: str) -> Optional[dict[str, Any]]:
        """Fetch a single record by primary key (id column)."""
        try:
            result = (
                self._client.table(self._table)
                .select("*")
                .eq("id", record_id)
                .single()
                .execute()
            )
            return result.data
        except Exception as exc:
            # .single() raises when no rows match — treat as not found
            logger.debug(f"get_by_id({self._table}, {record_id}) not found: {exc}")
            return None

    def list_all(
        self,
        filters: Optional[dict[str, Any]] = None,
        order_by: str = "created_at",
        ascending: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List records with optional equality filters."""
        query = self._client.table(self._table).select("*")

        if filters:
            for column, value in filters.items():
                query = query.eq(column, value)

        query = query.order(order_by, desc=not ascending).limit(limit)
        result = query.execute()
        return result.data or []

    # ── Write ─────────────────────────────────────────────────────────────────

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        """Insert a record and return the created row."""
        result = (
            self._client.table(self._table)
            .insert(data)
            .execute()
        )
        if not result.data:
            raise RuntimeError(f"Insert into {self._table} returned no data.")
        return result.data[0]

    def update(self, record_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update a record by id and return the updated row."""
        result = (
            self._client.table(self._table)
            .update(data)
            .eq("id", record_id)
            .execute()
        )
        if not result.data:
            raise RuntimeError(f"Update on {self._table}/{record_id} returned no data.")
        return result.data[0]

    def delete(self, record_id: str) -> bool:
        """Soft-delete by id. Returns True if a row was affected."""
        result = (
            self._client.table(self._table)
            .delete()
            .eq("id", record_id)
            .execute()
        )
        return bool(result.data)

    # ── Upsert ────────────────────────────────────────────────────────────────

    def upsert(self, data: dict[str, Any], on_conflict: str = "id") -> dict[str, Any]:
        """Insert or update based on conflict column."""
        result = (
            self._client.table(self._table)
            .upsert(data, on_conflict=on_conflict)
            .execute()
        )
        if not result.data:
            raise RuntimeError(f"Upsert on {self._table} returned no data.")
        return result.data[0]
