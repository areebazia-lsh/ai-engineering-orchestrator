import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from app.database.supabase_client import init_supabase_client
client = init_supabase_client()

print("Checking code_embeddings table...")
try:
    r = client.table("code_embeddings").select("id").limit(1).execute()
    print(f"  OK — table exists (rows sampled: {len(r.data)})")
except Exception as e:
    print(f"  FAIL: {e}")
    sys.exit(1)

print("Checking match_embeddings function...")
try:
    dummy = [0.0] * 384
    r = client.rpc("match_embeddings", {
        "query_embedding": dummy, "collection_filter": "code_knowledge",
        "match_count": 1, "similarity_threshold": 0.99, "project_id_filter": ""
    }).execute()
    print(f"  OK — function callable (rows: {len(r.data)})")
except Exception as e:
    print(f"  FAIL: {e}")
    sys.exit(1)

print("\nAll Phase 2 SQL checks passed.")
