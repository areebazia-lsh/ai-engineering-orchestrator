"""
Supabase pgvector store.

Stores and retrieves embedding vectors using the pgvector extension in Supabase.

Schema expected (see supabase_schema.sql — Phase 2 additions):
  Table: code_embeddings
    id           UUID PK
    project_id   UUID
    collection   VARCHAR(50)   -- code_knowledge | documentation_knowledge | bug_knowledge | project_knowledge
    chunk_id     TEXT UNIQUE   -- stable ID for upsert
    content      TEXT          -- raw_content shown to user
    embed_text   TEXT          -- what was embedded (context-enriched)
    embedding    vector(384)   -- pgvector column
    metadata     JSONB
    created_at   TIMESTAMPTZ

Similarity search uses cosine distance via pgvector's <=> operator
called through Supabase's rpc() with a custom Postgres function.

Design decisions:
  - Single table with a `collection` column rather than separate tables.
    This simplifies schema management and lets us filter by collection
    at query time — same pattern ChromaDB uses.
  - We upsert on chunk_id so re-ingesting the same repo doesn't create
    duplicates — it updates existing vectors instead.
  - The similarity search uses a Postgres RPC function (match_embeddings)
    that runs entirely in the database — no round-trips per candidate.
  - Scalability path: swap this class with a Pinecone/Weaviate implementation
    behind the same interface — nothing else changes.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from supabase import Client

logger = logging.getLogger(__name__)

# Collection name constants — match the architecture doc
COLLECTION_CODE          = "code_knowledge"
COLLECTION_DOCS          = "documentation_knowledge"
COLLECTION_BUGS          = "bug_knowledge"
COLLECTION_PROJECT       = "project_knowledge"

ALL_COLLECTIONS = [COLLECTION_CODE, COLLECTION_DOCS, COLLECTION_BUGS, COLLECTION_PROJECT]


class SupabaseVectorStore:
    """
    pgvector-backed vector store using Supabase.
    One instance per application — inject via app.state.
    """

    TABLE = "code_embeddings"
    MATCH_FUNCTION = "match_embeddings"

    def __init__(self, client: Client) -> None:
        self._client = client

    # ── Write ──────────────────────────────────────────────────────────────────

    def upsert(
        self,
        collection:  str,
        chunk_id:    str,
        content:     str,
        embed_text:  str,
        embedding:   list[float],
        metadata:    dict[str, Any],
        project_id:  str,
    ) -> dict[str, Any]:
        """
        Insert or update a single embedding record.
        Uses chunk_id as the conflict key so re-ingestion is idempotent.
        """
        record = {
            "collection":  collection,
            "chunk_id":    chunk_id,
            "project_id":  project_id,
            "content":     content,
            "embed_text":  embed_text,
            "embedding":   embedding,   # pgvector accepts Python list
            "metadata":    metadata,
        }
        result = (
            self._client.table(self.TABLE)
            .upsert(record, on_conflict="chunk_id")
            .execute()
        )
        return result.data[0] if result.data else {}

    def upsert_batch(
        self,
        records: list[dict[str, Any]],
    ) -> int:
        """
        Batch upsert for ingestion pipeline efficiency.
        Each record must have: collection, chunk_id, project_id,
        content, embed_text, embedding, metadata.
        Returns number of records upserted.
        """
        if not records:
            return 0

        # Supabase handles batch upsert natively
        result = (
            self._client.table(self.TABLE)
            .upsert(records, on_conflict="chunk_id")
            .execute()
        )
        count = len(result.data) if result.data else 0
        logger.debug(f"Upserted {count} vectors into {self.TABLE}")
        return count

    # ── Read ───────────────────────────────────────────────────────────────────

    def similarity_search(
        self,
        query_embedding:  list[float],
        collection:       str,
        project_id:       Optional[str] = None,
        top_k:            int = 8,
        similarity_threshold: float = 0.3,
    ) -> list[dict[str, Any]]:
        """
        Find the top_k most similar chunks to the query embedding.

        Returns list of dicts with keys:
          chunk_id, content, metadata, similarity (0.0–1.0)

        Uses the match_embeddings Postgres function (see supabase_schema.sql).
        """
        params: dict[str, Any] = {
            "query_embedding":    query_embedding,
            "collection_filter":  collection,
            "match_count":        top_k,
            "similarity_threshold": similarity_threshold,
        }
        if project_id:
            params["project_id_filter"] = project_id

        try:
            result = self._client.rpc(self.MATCH_FUNCTION, params).execute()
            return result.data or []
        except Exception as exc:
            logger.error(f"Similarity search failed: {exc}")
            return []

    def get_stats(self, project_id: Optional[str] = None) -> dict[str, int]:
        """Return chunk counts per collection."""
        stats: dict[str, int] = {}
        for col in ALL_COLLECTIONS:
            query = (
                self._client.table(self.TABLE)
                .select("id", count="exact")
                .eq("collection", col)
            )
            if project_id:
                query = query.eq("project_id", project_id)
            result = query.execute()
            stats[col] = result.count or 0
        return stats

    def delete_project(self, project_id: str) -> int:
        """Remove all vectors for a project (used when re-ingesting)."""
        result = (
            self._client.table(self.TABLE)
            .delete()
            .eq("project_id", project_id)
            .execute()
        )
        count = len(result.data) if result.data else 0
        logger.info(f"Deleted {count} vectors for project {project_id}")
        return count

    def delete_file(self, project_id: str, file_path: str) -> int:
        """Remove all vectors for a specific file in a project."""
        result = (
            self._client.table(self.TABLE)
            .delete()
            .eq("project_id", project_id)
            .eq("metadata->>source", file_path)
            .execute()
        )
        count = len(result.data) if result.data else 0
        logger.info(f"Deleted {count} vectors for file {file_path} in project {project_id}")
        return count
