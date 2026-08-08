"""
LangGraph shared state definition.

Design decisions:
- GraphState is a TypedDict — LangGraph requires this for typed state management.
- Every node receives the full state and returns a PARTIAL dict with only the keys
  it modifies. LangGraph merges these partial updates automatically.
- The `messages` field uses LangGraph's add_messages reducer so message lists are
  appended, not overwritten, when multiple nodes write to the same key.
- All fields are Optional where a node might not have populated them yet —
  this avoids KeyError access patterns in early graph nodes.
- `agent_steps` accumulates one entry per node execution for full observability.
  Each step is persisted as a trace record at the end of the graph run.
"""

from __future__ import annotations

from typing import Annotated, Any, Optional
from typing_extensions import TypedDict

from langgraph.graph.message import add_messages


# ── Step tracking type ─────────────────────────────────────────────────────────

class AgentStep(TypedDict):
    """A single agent execution step, collected into agent_steps for tracing."""
    agent:          str            # e.g. "router", "planner", "response_generator"
    input_summary:  str            # brief description of what this node received
    output_summary: str            # brief description of what this node produced
    tokens_used:    int            # LLM tokens consumed (0 for non-LLM nodes)


# ── Main graph state ───────────────────────────────────────────────────────────

class GraphState(TypedDict):
    """
    Single source of truth for the entire LangGraph execution.

    Lifecycle:
        Populated incrementally as nodes execute.
        Nodes read what they need, return partial updates.
        LangGraph merges updates before passing state to the next node.
    """

    # ── Identity ───────────────────────────────────────────────────────────
    session_id:   str            # UUID — links this run to a DB session
    project_id:   str            # UUID — which project this conversation is about

    # ── Input ─────────────────────────────────────────────────────────────
    user_message: str            # The raw message the user just sent

    # ── Conversation history ───────────────────────────────────────────────
    # add_messages reducer: new messages are appended, not replaced.
    # Format: list of {"role": ..., "content": ...} dicts
    messages: Annotated[list[dict[str, Any]], add_messages]

    # ── Context (populated by Context Manager node) ────────────────────────
    context: Optional[dict[str, Any]]
    # context structure:
    # {
    #   "history_summary": str,      # compressed conversation history
    #   "recent_messages": list,     # last N messages for immediate context
    #   "project_info": dict | None, # project metadata from DB
    # }

    # ── Router Agent output ────────────────────────────────────────────────
    intent:     Optional[str]    # e.g. "explain_code", "fix_bug", "generate_docs"
    workflow:   Optional[str]    # e.g. "code_debugging", "code_explanation"
    confidence: Optional[float]  # 0.0–1.0, how certain the router is

    # ── Planner Agent output ───────────────────────────────────────────────
    plan: Optional[list[dict[str, Any]]]
    # plan structure (list of steps):
    # [
    #   {"step": 1, "type": "retrieve_knowledge", "description": "...", "params": {}},
    #   {"step": 2, "type": "analyze_code",       "description": "...", "params": {}},
    #   ...
    # ]
    current_plan_step: int   # index into plan — which step we're currently executing

    # ── Phase 2: RAG / Knowledge retrieval ────────────────────────────────
    # Populated by KnowledgeAgent; read by ResponseGenerator.
    retrieved_code:  Optional[list[dict[str, Any]]]  # code chunks from vector store
    retrieved_docs:  Optional[list[dict[str, Any]]]  # doc chunks from vector store

    # ── Final response ─────────────────────────────────────────────────────
    final_response:  Optional[str]   # The answer text shown to the user
    response_type:   Optional[str]   # "text" | "patch" | "plan" | "test_results"

    # ── Phase 4: Code modification / patches ───────────────────────────────
    code_modification: Optional[dict[str, Any]]
    # code_modification structure:
    # {
    #   "target_file": str,           # File being modified
    #   "diff": str,                  # Unified diff content
    #   "applied": bool,              # Whether patch was applied
    #   "validation_error": str | None,
    #   "backup_path": str | None,
    #   "modified_content_preview": str,
    # }

    # ── Observability ──────────────────────────────────────────────────────
    agent_steps:  list[AgentStep]   # Accumulated trace entries — one per node
    total_tokens: int               # Running token count across all LLM calls
    error:        Optional[str]     # Set if any node hits an unrecoverable error
