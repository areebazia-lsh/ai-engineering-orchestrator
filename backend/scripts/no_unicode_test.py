import os, sys, traceback
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_DIR)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

print("Testing ingestion pipeline...")

try:
    # Test basic imports
    print("1. Testing imports...")
    from app.database.supabase_client import init_supabase_client
    print("   OK - supabase_client")
    
    from app.knowledge.vector_store.supabase_store import SupabaseVectorStore
    print("   OK - vector_store")
    
    from app.ingestion.parsers.python_ast_parser import PythonASTParser
    print("   OK - python_ast_parser")
    
    from app.ingestion.chunkers.code_chunker import CodeChunker
    print("   OK - code_chunker")
    
    from app.ingestion.embedder import embed_single
    print("   OK - embedder")
    
    from app.services.project_service import ProjectService
    print("   OK - project_service")
    
    print("\n2. Testing Supabase connection...")
    client = init_supabase_client()
    print("   OK - Connected to Supabase")
    
    print("\n3. Testing project creation...")
    svc = ProjectService(client)
    project = svc.create_project(
        name="Simple Test",
        description="Test project"
    )
    project_id = project["id"]
    print(f"   OK - Created project: {project_id}")
    
    print("\n4. Testing embedding...")
    vector = embed_single("test query")
    print(f"   OK - Vector dimension: {len(vector)}")
    
    print("\n5. Testing vector store...")
    vector_store = SupabaseVectorStore(client)
    
    # Test similarity search with dummy vector
    dummy_vector = [0.0] * 384
    results = vector_store.similarity_search(
        query_embedding=dummy_vector,
        collection="code_knowledge",
        project_id=project_id,
        top_k=2,
        similarity_threshold=0.1
    )
    print(f"   OK - Similarity search returned {len(results)} results")
    
    print("\nSUCCESS - All Phase 2 components working!")
    
except Exception as e:
    print(f"\nFAILED: {e}")
    traceback.print_exc()