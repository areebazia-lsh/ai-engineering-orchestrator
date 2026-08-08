"""
LangGraph workflow graph — Phase 6 (full agentic pipeline).

Phase 6 graph structure:
    START
      ↓
    context_manager
      ↓
    router_agent
      ↓ (error → response_generator)
    planner_agent
      ↓ (plan step type routing)
          retrieve_knowledge? → knowledge_agent
          code_intelligence?  → code_intelligence_agent
          generate_patch?    → coding_agent
          run_tests?        → testing_agent  ← NEW Phase 6
          validate?         → validation_agent  ← NEW Phase 6
          else              → response_generator
    knowledge_agent / code_intelligence_agent / coding_agent / testing_agent / validation_agent
      ↓
    response_generator
      ↓
    END

Retry logic:
  - If validation fails, planner retries with max 3 attempts
  - Each retry goes back to planner for plan regeneration
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from langgraph.graph import StateGraph, END, START

from app.models.llm_providers import BaseLLMProvider
from app.knowledge.vector_store.supabase_store import SupabaseVectorStore
from app.orchestration.state import GraphState
from app.orchestration.nodes import create_nodes
from app.orchestration.edges import (
    route_after_router,
    route_after_planner,
    route_after_knowledge,
    route_after_code_intelligence,
    route_after_coding,
    route_after_testing,
    route_after_validation,
)

logger = logging.getLogger(__name__)


def build_graph(
    llm: BaseLLMProvider,
    vector_store: Optional[SupabaseVectorStore] = None,
) -> Any:
    """
    Construct and compile the Phase 2 LangGraph workflow.

    Args:
        llm:          Initialised LLM provider.
        vector_store: Initialised SupabaseVectorStore.  If None the
                      knowledge_agent node will be registered but will
                      return empty results (safe degraded mode).
    Returns:
        Compiled LangGraph ready for ainvoke().
    """
    nodes = create_nodes(llm, vector_store=vector_store)

    graph = StateGraph(GraphState)

    # ── Register all nodes ────────────────────────────────────────────────────
    graph.add_node("context_manager",         nodes["context_manager"])
    graph.add_node("router_agent",            nodes["router_agent"])
    graph.add_node("planner_agent",           nodes["planner_agent"])
    graph.add_node("knowledge_agent",         nodes["knowledge_agent"])   # Phase 2
    graph.add_node("code_intelligence_agent", nodes["code_intelligence_agent"])  # Phase 3
    graph.add_node("coding_agent",            nodes["coding_agent"])      # Phase 4
    graph.add_node("testing_agent",           nodes["testing_agent"])     # Phase 6
    graph.add_node("validation_agent",        nodes["validation_agent"])  # Phase 6
    graph.add_node("response_generator",      nodes["response_generator"])

    # ── Edges ─────────────────────────────────────────────────────────────────
    graph.add_edge(START, "context_manager")
    graph.add_edge("context_manager", "router_agent")

    graph.add_conditional_edges(
        "router_agent",
        route_after_router,
        {
            "planner_agent":      "planner_agent",
            "response_generator": "response_generator",
        },
    )

    graph.add_conditional_edges(
        "planner_agent",
        route_after_planner,
        {
            "knowledge_agent":         "knowledge_agent",         # Phase 2
            "code_intelligence_agent": "code_intelligence_agent", # Phase 3
            "coding_agent":            "coding_agent",            # Phase 4
            "testing_agent":           "testing_agent",           # Phase 6
            "validation_agent":        "validation_agent",        # Phase 6
            "response_generator":      "response_generator",
        },
    )

    graph.add_conditional_edges(
        "knowledge_agent",
        route_after_knowledge,
        {
            "response_generator": "response_generator",
        },
    )

    graph.add_conditional_edges(
        "code_intelligence_agent",
        route_after_code_intelligence,
        {
            "response_generator": "response_generator",
        },
    )

    graph.add_conditional_edges(
        "coding_agent",
        route_after_coding,
        {
            "response_generator": "response_generator",
        },
    )

    graph.add_conditional_edges(
        "testing_agent",
        route_after_testing,
        {
            "validation_agent": "validation_agent",  # Go to validation after tests
            "response_generator": "response_generator",  # Or go directly if no tests run
        },
    )

    graph.add_conditional_edges(
        "validation_agent",
        route_after_validation,
        {
            "response_generator": "response_generator",
            "planner_agent": "planner_agent",  # Retry loop: fail → planner
        },
    )

    graph.add_edge("response_generator", END)

    compiled = graph.compile()

    logger.info(
        f"LangGraph compiled | nodes={list(nodes.keys())} "
        f"rag={'enabled' if vector_store else 'disabled'} "
        f"provider={llm.__class__.__name__}"
    )
    return compiled
