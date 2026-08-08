import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from app.database.supabase_client import init_supabase_client
client = init_supabase_client()

# Check if code_embeddings table exists
try:
    r = client.table("code_embeddings").select("id").limit(1).execute()
    print("✓ code_embeddings table exists")
    print(f"  Sample rows: {len(r.data)}")
except Exception as e:
    if "table" in str(e):
        print("✗ code_embeddings table NOT FOUND")
    else:
        print(f"✗ Error checking table: {e}")
    sys.exit(1)

# Check match_embeddings function
try:
    dummy = [0.0] * 384
    r = client.rpc("match_embeddings", {
        "query_embedding": dummy, "collection_filter": "code_knowledge",
        "match_count": 1, "similarity_threshold": 0.99, "project_id_filter": ""
    }).execute()
    print("✓ match_embeddings function exists")
except Exception as e:
    print(f"✗ match_embeddings function error: {e}")
    sys.exit(1)

print("\nPhase 2 SQL appears ready.")