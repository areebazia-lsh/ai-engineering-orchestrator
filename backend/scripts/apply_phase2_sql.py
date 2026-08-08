"""
Apply Phase 2 pgvector SQL directly via Supabase Management API.
Uses the service role key — no dashboard interaction needed.
Run from backend/:
    python scripts/apply_phase2_sql.py
"""
import os, sys, json, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings

# Extract project ref from URL: https://<ref>.supabase.co
project_ref = settings.SUPABASE_URL.replace("https://", "").split(".")[0]
api_url = f"https://api.supabase.com/v1/projects/{project_ref}/database/query"
token   = settings.SUPABASE_SERVICE_ROLE_KEY

# We'll run statements one at a time for clearer error reporting
STATEMENTS = [
    ("Enable pgvector extension",
     "CREATE EXTENSION IF NOT EXISTS vector;"),

    ("Create code_embeddings table", """
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
);"""),

    ("Create project index",
     "CREATE INDEX IF NOT EXISTS idx_embeddings_project    ON code_embeddings(project_id);"),
    ("Create collection index",
     "CREATE INDEX IF NOT EXISTS idx_embeddings_collection ON code_embeddings(collection);"),
    ("Create chunk_id index",
     "CREATE INDEX IF NOT EXISTS idx_embeddings_chunk_id   ON code_embeddings(chunk_id);"),

    ("Create match_embeddings function", """
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
$$;"""),
]

def run_sql(label: str, sql: str) -> bool:
    payload = json.dumps({"query": sql.strip()}).encode()
    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            print(f"  OK  — {label}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        # Parse error detail
        try:
            detail = json.loads(body)
            msg = detail.get("message") or detail.get("error") or body[:200]
        except Exception:
            msg = body[:200]
        # "already exists" errors are fine — idempotent
        if "already exists" in msg.lower():
            print(f"  OK  — {label} (already exists)")
            return True
        print(f"  FAIL — {label}: {msg}")
        return False

print("Applying Phase 2 SQL to Supabase...")
print(f"Project: {project_ref}\n")

all_ok = True
for label, sql in STATEMENTS:
    ok = run_sql(label, sql)
    if not ok:
        all_ok = False

if all_ok:
    print("\nAll statements applied successfully.")
else:
    print("\nSome statements failed. If the Management API is not available,")
    print("copy the Phase 2 block from supabase_schema.sql into the Supabase")
    print("SQL Editor (Dashboard → SQL Editor) and run it there.")
    sys.exit(1)
