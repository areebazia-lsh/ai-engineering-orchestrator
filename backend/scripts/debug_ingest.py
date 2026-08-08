import os, sys, traceback
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_DIR)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

print("Debug ingestion...")

try:
    # Test each component
    print("1. Testing imports...")
    from app.database.supabase_client import init_supabase_client
    print("  [OK] supabase_client")
    
    from app.knowledge.vector_store.supabase_store import SupabaseVectorStore
    print("  [OK] vector_store")
    
    from app.ingestion.parsers.python_ast_parser import PythonASTParser
    print("  [OK] python_ast_parser")
    
    from app.ingestion.chunkers.code_chunker import CodeChunker, EmbeddableChunk
    print("  ✓ code_chunker")
    
    from app.ingestion.embedder import embed_texts
    print("  ✓ embedder")
    
    from app.services.project_service import ProjectService
    print("  ✓ project_service")
    
    print("\n2. Testing Supabase connection...")
    client = init_supabase_client()
    print("  ✓ Connected")
    
    print("\n3. Testing project creation...")
    svc = ProjectService(client)
    project = svc.create_project(
        name="Debug Test Project",
        description="Debug ingestion"
    )
    project_id = project["id"]
    print(f"  ✓ Created project: {project_id}")
    
    print("\n4. Testing parser...")
    parser = PythonASTParser()
    test_file = "app/ingestion/embedder.py"
    chunks = parser.parse_file(test_file)
    print(f"  ✓ Parsed {test_file}: {len(chunks)} chunks")
    
    print("\n5. Testing chunker...")
    chunker = CodeChunker(project_id=project_id, project_name="Debug Test", language="python")
    if chunks:
        embeddable = chunker.chunk(chunks[0])
        print(f"  ✓ Chunked first parsed chunk: {len(embeddable)} embeddable chunks")
    
    print("\n✅ All components working!")
    
except Exception as e:
    print(f"\n[ERROR] {e}")
    traceback.print_exc()