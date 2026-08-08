import os, sys, time, traceback
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_DIR)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

print("Minimal ingestion test - just 2 files...")

try:
    # Initialize
    from app.database.supabase_client import init_supabase_client
    from app.knowledge.vector_store.supabase_store import SupabaseVectorStore
    from app.ingestion.parsers.python_ast_parser import PythonASTParser
    from app.ingestion.chunkers.code_chunker import CodeChunker, EmbeddableChunk
    from app.ingestion.embedder import embed_texts
    from app.services.project_service import ProjectService
    
    client = init_supabase_client()
    vector_store = SupabaseVectorStore(client)
    
    print("✓ Connected to Supabase")
    
    # Create a project
    svc = ProjectService(client)
    project = svc.create_project(
        name="Minimal Test Project",
        description="Test ingestion of 2 files"
    )
    project_id = project["id"]
    print(f"✓ Created project: {project_id}")
    
    # Initialize parser and chunker
    parser = PythonASTParser()
    chunker = CodeChunker(project_id=project_id, project_name="Minimal Test Project", language="python")
    
    # Process just 2 files
    test_files = [
        "app/ingestion/embedder.py",
        "app/ingestion/pipeline.py"
    ]
    
    all_chunks = []
    for file_path in test_files:
        if not os.path.exists(file_path):
            print(f"  Skipping {file_path} (not found)")
            continue
        
        print(f"  Parsing {file_path}...")
        chunks = parser.parse_file(file_path)
        print(f"    Found {len(chunks)} semantic chunks")
        
        for parsed_chunk in chunks:
            embeddable_chunks = chunker.chunk(parsed_chunk)
            all_chunks.extend(embeddable_chunks)
    
    print(f"\n✓ Total embeddable chunks: {len(all_chunks)}")
    
    # Embed and store
    if all_chunks:
        print("  Embedding chunks...")
        texts = [c.embed_text for c in all_chunks]
        embeddings = embed_texts(texts, batch_size=8)
        print(f"  Generated {len(embeddings)} embeddings")
        
        # Prepare records
        records = []
        for chunk, emb in zip(all_chunks, embeddings):
            records.append({
                "collection": "code_knowledge",
                "chunk_id": chunk.chunk_id,
                "project_id": chunk.metadata["project_id"],
                "content": chunk.raw_content,
                "embed_text": chunk.embed_text,
                "embedding": emb,
                "metadata": chunk.metadata,
            })
        
        # Upsert to Supabase
        print(f"  Upserting {len(records)} records to Supabase...")
        upserted = vector_store.upsert_batch(records)
        print(f"  ✓ Successfully upserted {upserted} vectors")
        
        # Verify
        stats = vector_store.get_stats(project_id=project_id)
        print(f"\n📊 Vector store stats:")
        for col, count in stats.items():
            print(f"  {col}: {count}")
    
    print(f"\n✅ Ingestion successful!")
    print(f"Project ID for testing: {project_id}")
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    traceback.print_exc()