import os, sys
import json, requests
from dotenv import load_dotenv
load_dotenv()

# Check Supabase directly
supabase_url = os.getenv("SUPABASE_URL")
service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

print("Checking Supabase tables...")
print(f"URL: {supabase_url}")
print(f"Key present: {'YES' if service_key else 'NO'}")

headers = {
    "apikey": service_key,
    "Authorization": f"Bearer {service_key}",
    "Content-Type": "application/json"
}

# Check code_embeddings
try:
    resp = requests.get(
        f"{supabase_url}/rest/v1/code_embeddings",
        params={"select": "id", "limit": 1},
        headers=headers
    )
    print(f"\n1. code_embeddings table: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"   ✓ EXISTS ({len(data)} rows)")
    elif resp.status_code == 404:
        print("   ✗ NOT FOUND - Table does not exist")
    else:
        print(f"   ? ERROR: {resp.text[:200]}")
except Exception as e:
    print(f"   ✗ REQUEST ERROR: {e}")

# Check projects table
try:
    resp = requests.get(
        f"{supabase_url}/rest/v1/projects",
        params={"select": "id", "limit": 1},
        headers=headers
    )
    print(f"\n2. projects table: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"   ✓ EXISTS ({len(data)} rows)")
    elif resp.status_code == 404:
        print("   ✗ NOT FOUND - Phase 1 schema not applied")
    else:
        print(f"   ? ERROR: {resp.text[:200]}")
except Exception as e:
    print(f"   ✗ REQUEST ERROR: {e}")

# Check match_embeddings function
try:
    dummy_vector = [0.0] * 384
    resp = requests.post(
        f"{supabase_url}/rest/v1/rpc/match_embeddings",
        json={
            "query_embedding": dummy_vector,
            "collection_filter": "code_knowledge",
            "match_count": 1,
            "similarity_threshold": 0.99,
            "project_id_filter": ""
        },
        headers=headers
    )
    print(f"\n3. match_embeddings function: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"   ✓ EXISTS (returned {len(data)} rows)")
    elif resp.status_code == 404:
        print("   ✗ NOT FOUND - Function does not exist")
    else:
        print(f"   ? ERROR: {resp.text[:200]}")
except Exception as e:
    print(f"   ✗ REQUEST ERROR: {e}")

print("\nSummary:")
print("-" * 50)
print("Phase 2 SQL should be run manually in Supabase Dashboard if any tables are missing.")
print("Copy the Phase 2 section from backend/supabase_schema.sql")