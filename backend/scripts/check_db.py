import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from app.database.supabase_client import init_supabase_client
client = init_supabase_client()

results = []
try:
    r = client.table("code_embeddings").select("id").limit(1).execute()
    results.append(f"code_embeddings: OK (rows={len(r.data)})")
except Exception as e:
    results.append(f"code_embeddings: FAIL - {e}")

try:
    dummy = [0.0] * 384
    r = client.rpc("match_embeddings", {
        "query_embedding": dummy, "collection_filter": "code_knowledge",
        "match_count": 1, "similarity_threshold": 0.99, "project_id_filter": ""
    }).execute()
    results.append(f"match_embeddings: OK (rows={len(r.data)})")
except Exception as e:
    results.append(f"match_embeddings: FAIL - {e}")

for line in results:
    print(line)
