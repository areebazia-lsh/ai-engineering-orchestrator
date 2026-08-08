"""
Supabase table setup / migration helper.

Since Supabase manages PostgreSQL for us, we don't use Alembic.
Instead, this module holds the SQL DDL for all Phase 1 tables and
provides a run_migrations() helper that executes them via the
Supabase Management API (rpc or raw SQL execution).

HOW TO USE:
  1. Run this once after setting up your Supabase project:
         python -m app.database.migrations
  2. Or call run_migrations() from the FastAPI lifespan on first boot
     (idempotent — uses CREATE TABLE IF NOT EXISTS).

NOTE: In production, manage schema changes via Supabase Dashboard migrations
or supabase CLI (`supabase db push`). This helper is for local/dev setup.
"""

from __future__ import annotations

import logging
from app.database.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

# ── DDL Statements ─────────────────────────────────────────────────────────────
# Order matters — foreign keys require parent tables to exist first.

PHASE_1_TABLES: list[tuple[str, str]] = [
    (
        "projects",
        """
        CREATE TABLE IF NOT EXISTS projects (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name                VARCHAR(255) NOT NULL,
            description         TEXT,
            repository_url      VARCHAR(500),
            repository_path     VARCHAR(500),
            primary_language    VARCHAR(50),
            ingestion_status    VARCHAR(50) DEFAULT 'pending',
            ingested_at         TIMESTAMPTZ,
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            updated_at          TIMESTAMPTZ DEFAULT NOW()
        );
        """,
    ),
    (
        "sessions",
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id  UUID REFERENCES projects(id) ON DELETE CASCADE,
            title       VARCHAR(255),
            status      VARCHAR(50) DEFAULT 'active',
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            updated_at  TIMESTAMPTZ DEFAULT NOW()
        );
        """,
    ),
    (
        "messages",
        """
        CREATE TABLE IF NOT EXISTS messages (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id  UUID REFERENCES sessions(id) ON DELETE CASCADE,
            role        VARCHAR(20) NOT NULL,
            content     TEXT NOT NULL,
            metadata    JSONB DEFAULT '{}',
            created_at  TIMESTAMPTZ DEFAULT NOW()
        );
        """,
    ),
    (
        "agent_traces",
        """
        CREATE TABLE IF NOT EXISTS agent_traces (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id      UUID REFERENCES sessions(id) ON DELETE CASCADE,
            message_id      UUID REFERENCES messages(id),
            workflow        VARCHAR(100),
            steps           JSONB NOT NULL DEFAULT '[]',
            total_tokens    INTEGER DEFAULT 0,
            duration_ms     INTEGER DEFAULT 0,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        );
        """,
    ),
    (
        "long_term_memory",
        """
        CREATE TABLE IF NOT EXISTS long_term_memory (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id      UUID REFERENCES projects(id) ON DELETE CASCADE,
            session_id      UUID REFERENCES sessions(id),
            memory_type     VARCHAR(50) NOT NULL,
            key             VARCHAR(255) NOT NULL,
            value           TEXT NOT NULL,
            importance      FLOAT DEFAULT 0.5,
            last_accessed   TIMESTAMPTZ,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(project_id, memory_type, key)
        );
        """,
    ),
]


def run_migrations(dry_run: bool = False) -> None:
    """
    Execute all Phase 1 DDL statements against Supabase.
    Uses rpc('exec_sql', ...) — requires the exec_sql function to be
    enabled in your Supabase project, OR paste the SQL directly in
    the Supabase SQL editor.

    Args:
        dry_run: If True, prints SQL without executing.
    """
    if dry_run:
        logger.info("=== DRY RUN — DDL statements that would be executed ===")
        for table_name, sql in PHASE_1_TABLES:
            print(f"\n-- Table: {table_name}\n{sql.strip()}")
        return

    client = get_supabase_client()

    for table_name, sql in PHASE_1_TABLES:
        try:
            # Supabase exposes a `postgres` RPC for raw SQL in some plans.
            # If not available, the SQL can be run via the Dashboard.
            client.rpc("exec_sql", {"query": sql.strip()}).execute()
            logger.info(f"Migration OK: {table_name}")
        except Exception as exc:
            logger.warning(
                f"Migration via RPC failed for {table_name}: {exc}\n"
                "Run the SQL manually in the Supabase Dashboard SQL editor."
            )


def get_migration_sql() -> str:
    """Return all DDL as a single SQL string for manual execution."""
    return "\n\n".join(sql.strip() for _, sql in PHASE_1_TABLES)


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from app.database.supabase_client import init_supabase_client

    init_supabase_client()

    if "--dry-run" in sys.argv:
        run_migrations(dry_run=True)
    elif "--print-sql" in sys.argv:
        print(get_migration_sql())
    else:
        run_migrations()
