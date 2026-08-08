import os, sys, time, json
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _BACKEND_DIR)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

print("Testing Phase 3 - Code Intelligence...")

try:
    print("\n1. Testing AST analyzer...")
    from app.analysis.ast_analyzer import ASTAnalyzer
    analyzer = ASTAnalyzer()
    
    test_file = os.path.join(_BACKEND_DIR, "app", "ingestion", "embedder.py")
    module_info = analyzer.analyze_file(test_file)
    if module_info:
        print("[OK] Analyzed file")
        print("     Functions: " + str(len(module_info.functions)))
        print("     Classes: " + str(len(module_info.classes)))
        print("     Imports: " + str(len(module_info.imports)))
        
        if module_info.functions:
            func = module_info.functions[0]
            print("     Sample function: " + func.name)
            print("       Parameters: " + str(func.parameters))
    else:
        print("[FAIL] No module info returned")
    
    print("\n2. Testing CodeIntelligenceAgent...")
    from app.agents.code_intelligence_agent import CodeIntelligenceAgent
    from app.models.llm_providers import create_llm_provider
    
    llm = create_llm_provider()
    agent = CodeIntelligenceAgent(llm)
    print("[OK] CodeIntelligenceAgent instantiated")
    
    print("\n3. Testing dependency graph builder...")
    from app.analysis.ast_analyzer import build_dependency_graph
    
    if module_info:
        graph = build_dependency_graph([module_info])
        print("[OK] Built dependency graph")
        print("     Functions: " + str(len(graph['functions'])))
        print("     Classes: " + str(len(graph['classes'])))
    
    print("\n[OK] Phase 3 components appear functional!")
    
except Exception as e:
    print("\n[ERROR] " + str(e))
    import traceback
    traceback.print_exc()