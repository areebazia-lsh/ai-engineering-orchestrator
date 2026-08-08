import os, sys, traceback
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_DIR)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

print("Simple ingestion test...")

try:
    # Initialize
    from app.database.supabase_client import init_supabase_client
    from app.knowledge.vector_store.supabase_store import SupabaseVectorStore
    from app.ingestion.pipeline import ingest_repository
    
    client = init_supabase_client()
    vector_store = SupabaseVectorStore(client)
    
    print("Connected to Supabase")
    
    # Create a project first
    from app.services.project_service import ProjectService
    svc = ProjectService(client)
    project = svc.create_project(
        name="Simple Test Project",
        description="Test ingestion"
    )
    project_id = project["id"]
    print(f"Created project: {project_id}")
    
    # Run ingestion
    result = ingest_repository(
        repo_path=".",
        project_id=project_id,
        project_name="Simple Test Project",
        vector_store=vector_store,
        clear_existing=False,
        progress_cb=lambda msg: print(f"  {msg}")
    )
    
    print(f"\nSuccess! Files: {result.files_processed}, Chunks: {result.chunks_created}")
    print(f"Vectors: {result.vectors_upserted}")
    
except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()