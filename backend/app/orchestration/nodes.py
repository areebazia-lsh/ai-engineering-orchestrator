"""
LangGraph node functions — Phase 3.

All nodes are thin async wrappers that inject dependencies via closure
and delegate to agent classes.  The factory pattern keeps agents
testable in isolation and makes dependency swapping trivial.

Phase 2 additions:
  - knowledge_agent_node  wraps KnowledgeAgent(llm, vector_store)
Phase 3 additions:
  - code_intelligence_agent_node wraps CodeIntelligenceAgent(llm)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from app.agents.context_manager import run_context_manager
from app.agents.router_agent import RouterAgent
from app.agents.planner_agent import PlannerAgent
from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.code_intelligence_agent import CodeIntelligenceAgent
from app.agents.coding_agent import CodingAgent
from app.agents.testing_agent import TestingAgent
from app.agents.validation_agent import ValidationAgent
from app.agents.response_generator import ResponseGeneratorAgent
from app.models.llm_providers import BaseLLMProvider
from app.knowledge.vector_store.supabase_store import SupabaseVectorStore
from app.orchestration.state import GraphState

logger = logging.getLogger(__name__)


def create_nodes(
    llm: BaseLLMProvider,
    vector_store: Optional[SupabaseVectorStore] = None,
) -> dict[str, Callable]:
    """
    Dependency-inject all agents and return a node-name → async-function map.

    Args:
        llm:          LLM provider (shared across all LLM-using agents).
        vector_store: Vector store for KnowledgeAgent.  Pass None to run
                      in degraded mode (knowledge node returns empty results).
    """

    router                = RouterAgent(llm)
    planner               = PlannerAgent(llm)
    knowledge             = KnowledgeAgent(llm, vector_store) if vector_store else None
    code_intelligence     = CodeIntelligenceAgent(llm)
    coding                = CodingAgent(llm)
    testing               = TestingAgent(llm)
    validation            = ValidationAgent(llm)
    response_generator    = ResponseGeneratorAgent(llm)

    async def context_manager_node(state: GraphState) -> dict[str, Any]:
        logger.debug(f"[NODE] context_manager | session={state['session_id']}")
        return await run_context_manager(state, llm)

    async def router_agent_node(state: GraphState) -> dict[str, Any]:
        logger.debug(f"[NODE] router_agent | session={state['session_id']}")
        return await router.run(state)

    async def planner_agent_node(state: GraphState) -> dict[str, Any]:
        logger.debug(f"[NODE] planner_agent | session={state['session_id']}")
        return await planner.run(state)

    async def knowledge_agent_node(state: GraphState) -> dict[str, Any]:
        logger.debug(f"[NODE] knowledge_agent | session={state['session_id']}")
        if knowledge is None:
            # Degraded — no vector store configured
            logger.warning("KnowledgeAgent called but no vector_store configured — returning empty")
            existing_steps = state.get("agent_steps") or []
            from app.orchestration.state import AgentStep
            step: AgentStep = {
                "agent": "knowledge_agent",
                "input_summary": "no vector store",
                "output_summary": "skipped — vector store not configured",
                "tokens_used": 0,
            }
            return {
                "retrieved_code": [],
                "retrieved_docs": [],
                "agent_steps": existing_steps + [step],
                "total_tokens": state.get("total_tokens") or 0,
            }
        return await knowledge.run(state)

    async def code_intelligence_agent_node(state: GraphState) -> dict[str, Any]:
        logger.debug(f"[NODE] code_intelligence_agent | session={state['session_id']}")
        return await code_intelligence.run(state)

    async def coding_agent_node(state: GraphState) -> dict[str, Any]:
        logger.debug(f"[NODE] coding_agent | session={state['session_id']}")
        return await coding.run(state)

    async def testing_agent_node(state: GraphState) -> dict[str, Any]:
        logger.debug(f"[NODE] testing_agent | session={state['session_id']}")
        return await testing.run(state)

    async def validation_agent_node(state: GraphState) -> dict[str, Any]:
        logger.debug(f"[NODE] validation_agent | session={state['session_id']}")
        return await validation.run(state)

    async def response_generator_node(state: GraphState) -> dict[str, Any]:
        logger.debug(f"[NODE] response_generator | session={state['session_id']}")
        return await response_generator.run(state)

    return {
        "context_manager":         context_manager_node,
        "router_agent":            router_agent_node,
        "planner_agent":           planner_agent_node,
        "knowledge_agent":         knowledge_agent_node,
        "code_intelligence_agent": code_intelligence_agent_node,
        "coding_agent":            coding_agent_node,
        "testing_agent":           testing_agent_node,
        "validation_agent":        validation_agent_node,
        "response_generator":      response_generator_node,
    }
