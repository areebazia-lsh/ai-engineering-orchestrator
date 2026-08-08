import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

print("Testing ingestion components...")

# Test 1: Check embedder
print("\n1. Testing embedder...")
try:
    from app.ingestion.embedder import embed_single
    result = embed_single("test embedding")
    print(f"   ✓ Embedder works: vector length = {len(result)}")
except Exception as e:
    print(f"   ✗ Embedder failed: {e}")

# Test 2: Check Python AST parser
print("\n2. Testing Python AST parser...")
try:
    from app.ingestion.parsers.python_ast_parser import PythonASTParser
    parser = PythonASTParser()
    # Parse this script
    test_file = __file__
    chunks = parser.parse_file(test_file)
    print(f"   ✓ Parser works: found {len(chunks)} chunks")
    for i, chunk in enumerate(chunks[:3]):
        print(f"     Chunk {i}: {chunk.chunk_type} '{chunk.name}'")
except Exception as e:
    print(f"   ✗ Parser failed: {e}")

# Test 3: Check Supabase connection
print("\n3. Testing Supabase connection...")
try:
    from app.database.supabase_client import init_supabase_client
    client = init_supabase_client()
    # Check code_embeddings table
    result = client.table("code_embeddings").select("id").limit(1).execute()
    print(f"   ✓ Supabase connected: code_embeddings table accessible")
except Exception as e:
    print(f"   ✗ Supabase connection failed: {e}")

print("\n---")
print("All tests complete. Run ingestion with:")
print("python scripts/ingest_repo.py --path . --name 'Test Project' --clear")