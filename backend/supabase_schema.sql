-- ════════════════════════════════════════════════════════════
--   AI Engineering Orchestrator — Phase 1 Database Schema
--   Run this once in your Supabase project:
--   Supabase Dashboard → SQL Editor → paste and run
-- ════════════════════════════════════════════════════════════

-- Enable UUID generation (already enabled in Supabase by default)
-- CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Projects ───────────────────────────────────────────────────────────────────
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

-- ── Sessions ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID REFERENCES projects(id) ON DELETE CASCADE,
    title       VARCHAR(255),
    status      VARCHAR(50) DEFAULT 'active',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── Messages ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS messages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID REFERENCES sessions(id) ON DELETE CASCADE,
    role        VARCHAR(20) NOT NULL,   -- user | assistant | system | tool
    content     TEXT NOT NULL,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── Agent Traces ───────────────────────────────────────────────────────────────
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

-- ── Long-Term Memory ───────────────────────────────────────────────────────────
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

-- ── Indexes for query performance ─────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_sessions_project_id     ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_messages_session_id     ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at     ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_agent_traces_session_id ON agent_traces(session_id);
CREATE INDEX IF NOT EXISTS idx_long_term_memory_project ON long_term_memory(project_id);

-- ════════════════════════════════════════════════════════════
--   Phase 2 — pgvector Knowledge Base
--   Run this AFTER Phase 1 schema (or together in one pass).
--   Supabase Dashboard → SQL Editor → paste and run
-- ════════════════════════════════════════════════════════════

-- Enable the pgvector extension (available on all Supabase projects)
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Embeddings table ──────────────────────────────────────────────────────────
-- Single table for all four collections (code, docs, bugs, project).
-- Filtered by the `collection` column at query time.
CREATE TABLE IF NOT EXISTS code_embeddings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID REFERENCES projects(id) ON DELETE CASCADE,
    collection  VARCHAR(50)  NOT NULL,   -- code_knowledge | documentation_knowledge | bug_knowledge | project_knowledge
    chunk_id    TEXT         NOT NULL,   -- stable ID used for upsert de-duplication
    content     TEXT         NOT NULL,   -- raw source/doc text returned to the agent
    embed_text  TEXT         NOT NULL,   -- context-enriched text that was embedded
    embedding   vector(384)  NOT NULL,   -- BAAI/bge-small-en-v1.5 = 384 dims
    metadata    JSONB        DEFAULT '{}',
    created_at  TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE(chunk_id)
);

-- Standard indexes
CREATE INDEX IF NOT EXISTS idx_embeddings_project    ON code_embeddings(project_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_collection ON code_embeddings(collection);
CREATE INDEX IF NOT EXISTS idx_embeddings_chunk_id   ON code_embeddings(chunk_id);

-- IVFFlat index for fast approximate nearest-neighbour search.
-- lists=100 is a good default for up to ~1M vectors.
-- Run AFTER bulk inserting data: the index performs better on populated tables.
-- Cosine distance matches the similarity metric used in match_embeddings().
CREATE INDEX IF NOT EXISTS idx_embeddings_vector
    ON code_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- ── Similarity search function ────────────────────────────────────────────────
-- Called by SupabaseVectorStore.similarity_search() via client.rpc().
-- Returns rows ordered by cosine similarity (highest first).
-- project_id_filter is optional — pass empty string '' to search all projects.
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

-- ════════════════════════════════════════════════════════════
--   Phase 4 — Patch History
-- ════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS patch_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID REFERENCES projects(id) ON DELETE CASCADE,
    session_id      UUID REFERENCES sessions(id),
    file_path       TEXT NOT NULL,
    original_hash   TEXT NOT NULL,
    patch_content   TEXT NOT NULL,
    applied_by      VARCHAR(100),  -- 'agent' | 'user'
    applied_at      TIMESTAMPTZ DEFAULT NOW(),
    rolled_back_at  TIMESTAMPTZ,
    rollback_reason TEXT,
    metadata        JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_patch_history_project ON patch_history(project_id);
CREATE INDEX IF NOT EXISTS idx_patch_history_file ON patch_history(file_path);
