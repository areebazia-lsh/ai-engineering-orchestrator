import os, sys, json, requests
from dotenv import load_dotenv
load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

print("Checking existing vectors in code_embeddings...")

headers = {
    "apikey": service_key,
    "Authorization": f"Bearer {service_key}",
    "Content-Type": "application/json"
}

# Count total vectors
resp = requests.get(
    f"{supabase_url}/rest/v1/code_embeddings",
    params={"select": "id", "count": "exact"},
    headers=headers
)
if resp.status_code == 200:
    count = int(resp.headers.get("content-range", "0").split("/")[-1]) if "content-range" in resp.headers else 0
    print(f"Total vectors in code_embeddings: {count}")
else:
    print(f"Error counting vectors: {resp.status_code}")
    print(resp.text[:200])

# Count by collection
resp = requests.get(
    f"{supabase_url}/rest/v1/code_embeddings",
    params={"select": "collection"},
    headers=headers
)
if resp.status_code == 200:
    data = resp.json()
    collections = {}
    for item in data:
        col = item["collection"]
        collections[col] = collections.get(col, 0) + 1
    print("\nVectors by collection:")
    for col, cnt in collections.items():
        print(f"  {col}: {cnt}")
else:
    print(f"Error fetching collections: {resp.status_code}")