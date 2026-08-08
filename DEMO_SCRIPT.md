# AI Engineering Orchestrator - Demo Script

This script walks through the key features of the AI Engineering Orchestrator. Run it line by line in front of your audience.

## Prerequisites

1. Backend running: `cd backend && uvicorn app.main:app --reload`
2. Frontend running: `cd frontend && npm run dev`
3. Open http://localhost:3000 in your browser

---

## Demo 1: Chat with Your Codebase (Phase 1-2)

**Objective**: Show conversational code understanding with RAG

```
1. In the chat, ask: "What does the embed_single function do?"
2. Watch the agent steps - it should:
   - Router directs to Planner
   - Planner calls retrieve_knowledge
   - KnowledgeAgent retrieves relevant code from vector store
   - ResponseGenerator synthesizes answer
3. The answer should reference actual code from embedder.py
```

**Expected outcome**: Agent retrieves and explains actual code from your repository.

---

## Demo 2: Code Intelligence (Phase 3)

**Objective**: Show deep code structure analysis

```
1. Ask: "What does embed_single depend on?"
2. Watch the agent steps:
   - Planner calls code_intelligence
   - CodeIntelligenceAgent analyzes the code
   - Shows function signature, dependencies
3. The answer should show: embed_single → embed_texts → _get_model → TextEmbedding
```

**Expected outcome**: Agent understands dependency relationships in your code.

---

## Demo 3: Bug Fix with Patch Generation (Phase 4)

**Objective**: Show code modification workflow

```
1. Ask: "Fix the typo in the comment at line 12 of embedder.py"
   (Or request any small, specific change)

2. Watch the agent steps:
   - Planner calls retrieve_knowledge (to get context)
   - Planner calls generate_patch (to create modification)
   - CodingAgent generates a unified diff

3. The frontend shows the DiffViewer with:
   - Green lines: additions
   - Red lines: deletions
   - Approve/Reject buttons

4. Click "Approve & Apply"
5. The patch is recorded in patch_history table
```

**Expected outcome**: A working unified diff is generated and approved.

---

## Demo 4: Testing Automation (Phase 6)

**Objective**: Show automated test generation

```
1. Ask: "Write a test for the embed_texts function"

2. Watch the agent steps:
   - Planner calls retrieve_knowledge (to get function context)
   - Planner calls run_tests
   - TestingAgent generates pytest code
   - TestRunner executes tests in subprocess

3. The validation agent checks:
   - Syntax is valid
   - Tests pass
   - No regressions

4. If validation passes, the final response includes test code
```

**Expected outcome**: A working pytest test is generated and validated.

---

## Demo 5: Full Agentic Loop (Phase 6)

**Objective**: Show end-to-end workflow

```
1. Ask: "Fix the typo in embedder.py and generate tests for it"

2. Watch the full pipeline:
   - Context Manager builds conversation history
   - Router analyzes intent
   - Planner creates multi-step plan:
     * retrieve_knowledge
     * generate_patch
     * run_tests
     * validate
     * respond

3. Agents execute in sequence:
   KnowledgeAgent → CodingAgent → TestingAgent → ValidationAgent → ResponseGenerator

4. If validation fails, the system retries (up to 3 times)

5. Final response includes:
   - Summary of changes
   - Test results
   - Confirmation of application
```

**Expected outcome**: Complete agentic loop executes successfully.

---

## Demo 6: Long-Term Memory (Phase 5)

**Objective**: Show memory persistence across sessions

```
1. In your current session, say:
   "I always want to use 4 spaces for indentation in this project"

2. The system stores this as a preference in long_term_memory

3. Start a NEW session (or restart backend)
4. Ask: "What's my project's indentation preference?"

5. The response should mention the saved preference

6. Or ask about code - the conversation context is summarized
   every 20 messages to keep prompts efficient
```

**Expected outcome**: Memory persists across sessions.

---

## Demo 7: Ingestion Workflow

**Objective**: Show file ingestion into knowledge base

```
1. In the frontend, click "Upload Files for Ingestion"
2. Select some .py files from your repository
3. Or use the CLI:
   python scripts/ingest_repo.py --path . --name "Demo Project"

4. Watch the stats update:
   - Files processed
   - Chunks created
   - Vectors stored

5. Check the knowledge base count - it should increase
```

**Expected outcome**: Files are ingested and searchable.

---

## Cleanup

```
# If you need to reset the system:
1. Delete vectors: client.table("code_embeddings").delete().eq("project_id", "...").execute()
2. Or run: python scripts/run_phase2_sql.py (to recreate tables)
3. Or just delete the Supabase project and start fresh
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Agent returns "no code found" | Run ingestion on your project first |
| Agent can't connect to Supabase | Check SUPABASE_URL and key in .env |
| Frontend can't connect to backend | Check NEXT_PUBLIC_API_URL in frontend/.env |
| Ingestion fails | Check file permissions and paths |
| Tests timeout | Increase timeout in testing_agent.py |

---

## Questions for Audience

1. Which phase would be most useful for your team?
2. What other capabilities would you add?
3. How would you use the memory system?

---

## Summary

This demo showed:
- ✅ Conversational code understanding with RAG
- ✅ Deep code structure analysis
- ✅ Automated patch generation
- ✅ Test generation and validation
- ✅ Long-term memory persistence
- ✅ Full agentic pipeline execution