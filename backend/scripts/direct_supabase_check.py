import os, sys, json, http.client, ssl, time
from dotenv import load_dotenv
load_dotenv()

# Supabase connection details
supabase_url = os.getenv("SUPABASE_URL")
anon_key = os.getenv("SUPABASE_ANON_KEY")
service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

print("Supabase URL:", supabase_url)
print("Project Ref:", supabase_url.replace("https://", "").split(".")[0])
print()

# Use service role key for PostgREST API
headers = {
    "apikey": service_key,
    "Authorization": f"Bearer {service_key}",
    "Content-Type": "application/json"
}

# Disable SSL verification for testing
context = ssl._create_unverified_context()
conn = http.client.HTTPSConnection(supabase_url.replace("https://", "").split(".")[0] + ".supabase.co", context=context)

print("1. Checking code_embeddings table...")
conn.request("GET", "/rest/v1/code_embeddings?select=id&limit=1", headers=headers)
resp = conn.getresponse()
if resp.status == 200:
    data = resp.read().decode()
    rows = json.loads(data)
    print(f"   ✓ Table exists ({len(rows)} rows in sample)")
else:
    print(f"   ✗ Table missing: {resp.status} {resp.reason}")
    body = resp.read().decode()
    print(f"   Body: {body[:200]}")
    print()
    print("ACTION REQUIRED: Run Phase 2 SQL in Supabase Dashboard → SQL Editor")
    print("Copy from: backend/supabase_schema.sql (lines 44 to end)")
    sys.exit(1)

print("\n2. Checking match_embeddings function...")
# Try to call the function with dummy data
dummy_vector = [0.0] * 384
payload = json.dumps({
    "query_embedding": dummy_vector,
    "collection_filter": "code_knowledge",
    "match_count": 1,
    "similarity_threshold": 0.99,
    "project_id_filter": ""
})
conn.request("POST", "/rest/v1/rpc/match_embeddings", body=payload, headers=headers)
resp = conn.getresponse()
if resp.status == 200:
    data = resp.read().decode()
    rows = json.loads(data)
    print(f"   ✓ Function exists, returned {len(rows)} rows")
else:
    print(f"   ✗ Function error: {resp.status} {resp.reason}")
    body = resp.read().decode()
    print(f"   Body: {body[:200]}")
    sys.exit(1)

print("\n3. Checking projects table (Phase 1)...")
conn.request("GET", "/rest/v1/projects?select=id&limit=1", headers=headers)
resp = conn.getresponse()
if resp.status == 200:
    data = resp.read().decode()
    rows = json.loads(data)
    print(f"   ✓ Projects table exists ({len(rows)} rows)")
else:
    print(f"   ✗ Projects table missing: {resp.status} {resp.reason}")
    print("   Phase 1 schema may not be applied")
    sys.exit(1)

print("\n✓ All Phase 2 database checks passed!")
print("Ready for ingestion.")
conn.close()