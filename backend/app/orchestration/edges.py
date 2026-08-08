"""
LangGraph conditional edge logic — Phase 3.

Routing rules:
  after context_manager  → router_agent  (always)
  after router_agent     → planner_agent | response_generator (error shortcut)
  after planner_agent    → knowledge_agent | code_intelligence_agent | response_generator
  after knowledge_agent  → response_generator
  after code_intelligence_agent → response_generator

Phase 2: knowledge_agent for retrieve_knowledge
Phase 3: code_intelligence_agent for code_intelligence
"""

from __future__ import annotations

import logging
from app.orchestration.state import GraphState

logger = logging.getLogger(__name__)

# Step types that are implemented and have a real node
IMPLEMENTED_STEPS = {
    "retrieve_knowledge": "knowledge_agent",
    "code_intelligence":  "code_intelligence_agent",
    "generate_patch":     "coding_agent",
    "run_tests":          "testing_agent",
    "validate":           "validation_agent",
}


def route_after_router(state: GraphState) -> str:
    if state.get("error"):
        logger.warning(
            f"Router error → response_generator | session={state['session_id']}"
        )
        return "response_generator"
    return "planner_agent"


def route_after_planner(state: GraphState) -> str:
    if state.get("error"):
        logger.warning(
            f"Planner error → response_generator | session={state['session_id']}"
        )
        return "response_generator"

    plan = state.get("plan") or []
    if not plan:
        return "response_generator"

    # Phase 4: If plan contains generate_patch step, route to coding_agent
    # (even if retrieve_knowledge comes first, we need coding_agent for patch generation)
    has_generate_patch = any(step.get("type") == "generate_patch" for step in plan)
    if has_generate_patch:
        logger.info(
            f"Planner → generate_patch → coding_agent | session={state['session_id']}"
        )
        return "coding_agent"

    # Find the first non-respond step that is actually executable now
    for step in plan:
        step_type = step.get("type", "respond")
        if step_type == "respond":
            continue
        if step_type in IMPLEMENTED_STEPS:
            node = IMPLEMENTED_STEPS[step_type]
            logger.info(
                f"Planner → {step_type} → {node} | session={state['session_id']} "
                f"step={step.get('step')}"
            )
            return node
        # Phase 4+ step — not yet implemented, fall through
        logger.debug(
            f"Step type '{step_type}' not yet implemented, falling to response_generator"
        )

    return "response_generator"


def route_after_knowledge(state: GraphState) -> str:
    """After knowledge retrieval always go to response_generator."""
    if state.get("error"):
        logger.warning(
            f"Knowledge error → response_generator | session={state['session_id']}"
        )
    return "response_generator"


def route_after_code_intelligence(state: GraphState) -> str:
    """After code intelligence always go to response_generator."""
    if state.get("error"):
        logger.warning(
            f"Code intelligence error → response_generator | session={state['session_id']}"
        )
    return "response_generator"


def route_after_coding(state: GraphState) -> str:
    """After coding go to testing (if tests needed) or validation/response."""
    if state.get("error"):
        logger.warning(
            f"Coding error → response_generator | session={state['session_id']}"
        )
        return "response_generator"
    
    # Check if tests are needed based on context
    context = state.get("context") or {}
    if context.get("test_generation"):
        return "testing_agent"
    
    # Otherwise go to validation
    return "validation_agent"


def route_after_testing(state: GraphState) -> str:
    """After testing go to validation."""
    if state.get("error"):
        logger.warning(
            f"Testing error → response_generator | session={state['session_id']}"
        )
        return "response_generator"
    return "validation_agent"


def route_after_validation(state: GraphState) -> str:
    """
    After validation:
    - If approved: go to response_generator
    - If failed and retries < max: go back to planner (retry)
    - If failed and max retries: go to response_generator with error
    """
    if state.get("error"):
        logger.warning(
            f"Validation error → response_generator | session={state['session_id']}"
        )
        return "response_generator"
    
    validation = state.get("validation") or {}
    approved = validation.get("approved", False)
    
    if approved:
        logger.info(
            f"Validation passed → response_generator | session={state['session_id']}"
        )
        return "response_generator"
    else:
        logger.info(
            f"Validation failed → retry to planner | session={state['session_id']}"
        )
        return "planner_agent"
