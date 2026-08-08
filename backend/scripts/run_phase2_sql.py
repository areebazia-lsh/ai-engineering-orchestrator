"""
One-shot script: run the Phase 2 pgvector SQL against Supabase.
Run from backend/ with the ai-orchestrator env active:
    python scripts/run_phase2_sql.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PHASE2_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS code_embeddings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID REFERENCES projects(id) ON DELETE CASCADE,
    collection  VARCHAR(50)  NOT NULL,
    chunk_id    TEXT         NOT NULL,
    content     TEXT         NOT NULL,
    embed_text  TEXT         NOT NULL,
    embedding   vector(384)  NOT NULL,
    metadata    JSONB        DEFAULT '{}',
    created_at  TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE(chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_embeddings_project    ON code_embeddings(project_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_collection ON code_embeddings(collection);
CREATE INDEX IF NOT EXISTS idx_embeddings_chunk_id   ON code_embeddings(chunk_id);

CREATE OR REPLACE FUNCTION match_embeddings(
    query_embedding       vector(384),
    collection_filter     varchar(50),
    match_count           int     DEFAULT 8,
    similarity_threshold  float   DEFAULT 0.3,
    project_id_filter     text    DEFAULT ''
)
RETURNS TABLE (
    chunk_id    text,
    content     text,
    metadata    jsonb,
    similarity  float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        e.chunk_id,
        e.content,
        e.metadata,
        1 - (e.embedding <=> query_embedding) AS similarity
    FROM code_embeddings e
    WHERE
        e.collection = collection_filter
        AND (project_id_filter = '' OR e.project_id::text = project_id_filter)
        AND 1 - (e.embedding <=> query_embedding) >= similarity_threshold
    ORDER BY e.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
"""

from app.database.supabase_client import init_supabase_client

client = init_supabase_client()

# Supabase exposes pg_execute via the Management API on paid plans.
# On free tier: paste PHASE2_SQL directly into Supabase SQL Editor.
# This script tests connectivity by checking if the table exists.
print("Checking Supabase connection...")
try:
    result = client.table("code_embeddings").select("id").limit(1).execute()
    print(f"OK — code_embeddings table exists (rows in sample: {len(result.data)})")
except Exception as exc:
    print(f"FAIL — code_embeddings table not found: {exc}")
    print("\nAction required:")
    print("  1. Open Supabase Dashboard → SQL Editor")
    print("  2. Copy the Phase 2 block from backend/supabase_schema.sql")
    print("  3. Paste and click Run")
    sys.exit(1)

# Verify the match_embeddings function exists
print("Checking match_embeddings function...")
try:
    dummy = [0.0] * 384
    result = client.rpc("match_embeddings", {
        "query_embedding":    dummy,
        "collection_filter":  "code_knowledge",
        "match_count":        1,
        "similarity_threshold": 0.99,
        "project_id_filter":  "",
    }).execute()
    print(f"OK — match_embeddings function works (returned {len(result.data)} rows)")
except Exception as exc:
    print(f"FAIL — match_embeddings function error: {exc}")
    sys.exit(1)

print("\nPhase 2 SQL verified. Ready for ingestion.")
