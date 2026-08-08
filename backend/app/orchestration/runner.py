"""
Graph execution runner.

This module is the single entry point for all agent workflow invocations.
API routes call run_graph() — they never interact with LangGraph directly.

Responsibilities:
  1. Load conversation history from the database and inject into initial state.
  2. Build the initial GraphState from the incoming request.
  3. Invoke the compiled graph.
  4. Persist the assistant message and agent trace back to Supabase.
  5. Return a clean RunResult to the API layer.

Error handling strategy:
  - If the graph itself raises (e.g., LangGraph internal error), we catch it
    here, log it, and return a structured error result. The API will translate
    this into an appropriate HTTP response.
  - Individual agent errors are already handled inside each node via
    _error_state() — they set state["error"] and the graph continues to
    response_generator which surfaces the error gracefully.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app.orchestration.state import GraphState, AgentStep
from app.services.session_service import SessionService, MessageService
from app.services.trace_service import TraceService
from app.database.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


# ── Result type ────────────────────────────────────────────────────────────────

@dataclass
class RunResult:
    """The structured output returned to the API layer after graph execution."""
    session_id:    str
    intent:        Optional[str]
    workflow:      Optional[str]
    plan:          list[dict[str, Any]]
    response:      str
    response_type: str
    total_tokens:  int
    duration_ms:   int
    agent_steps:   list[AgentStep]
    error:         Optional[str] = None
    code_modification: Optional[dict[str, Any]] = None  # Phase 4: Patch data from coding agent

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id":    self.session_id,
            "intent":        self.intent,
            "workflow":      self.workflow,
            "plan":          self.plan,
            "response":      self.response,
            "response_type": self.response_type,
            "total_tokens":  self.total_tokens,
            "duration_ms":   self.duration_ms,
            "agent_steps":   self.agent_steps,
            "error":         self.error,
            "code_modification": self.code_modification,
        }


# ── Runner ─────────────────────────────────────────────────────────────────────

async def run_graph(
    compiled_graph: Any,
    orchestration_nodes: dict[str, Callable],
    session_id: str,
    project_id: str,
    user_message: str,
    agent_mode: str = "auto",
    config: Optional[dict[str, Any]] = None,
) -> RunResult:
    """
    Execute the LangGraph workflow for a single user turn.

    Args:
        compiled_graph:     The compiled LangGraph from build_graph().
        orchestration_nodes: Dict of node_name → node_function for agent execution.
        session_id:         Active session UUID.
        project_id:         Project UUID this session belongs to.
        user_message:       The raw text message from the user.
        agent_mode:         "auto" for full workflow, or specific agent name.
        config:             Optional LangGraph run config (e.g., recursion_limit).

    Returns:
        RunResult with the response and full trace metadata.
    """
    start_time = time.monotonic()
    client = get_supabase_client()
    msg_service = MessageService(client)
    session_service = SessionService(client)
    trace_service = TraceService(client)

    # ── 1. Persist the user message ────────────────────────────────────────────
    try:
        msg_service.add_message(
            session_id=session_id,
            role="user",
            content=user_message,
        )
    except Exception as exc:
        logger.warning(f"Failed to persist user message: {exc}")

    # ── 2. Load conversation history ───────────────────────────────────────────
    try:
        history = msg_service.get_messages(session_id, limit=50)
        # Convert to simple role/content dicts for the state
        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in history
        ]
    except Exception as exc:
        logger.warning(f"Failed to load conversation history: {exc}")
        messages = [{"role": "user", "content": user_message}]

    # ── 3. Build initial GraphState ────────────────────────────────────────────
    initial_state: GraphState = {
        "session_id":       session_id,
        "project_id":       project_id,
        "user_message":     user_message,
        "messages":         messages,
        "context":          None,
        "intent":           None,
        "workflow":         None,
        "confidence":       None,
        "plan":             None,
        "current_plan_step": 0,
        # Phase 2 RAG fields
        "retrieved_code":   None,
        "retrieved_docs":   None,
        "final_response":   None,
        "response_type":    "text",
        # Phase 4: code modification
        "code_modification": None,
        "agent_steps":      [],
        "total_tokens":     0,
        "error":            None,
    }
    
    # ── Handle single agent mode ───────────────────────────────────────────────
    if agent_mode != "auto" and agent_mode in orchestration_nodes:
        logger.info(f"Running single agent: {agent_mode}")
        node_func = orchestration_nodes[agent_mode]
        
        # For some agents, we need to inject state that would normally come from previous nodes
        if agent_mode == "context_manager":
            # context_manager expects session_id, user_message
            pass
        elif agent_mode == "router_agent":
            initial_state["context"] = None
        elif agent_mode == "planner_agent":
            initial_state["intent"] = user_message  # Simplified - router would set this normally
        elif agent_mode == "knowledge_agent":
            initial_state["intent"] = "retrieve_knowledge"
        elif agent_mode == "code_intelligence_agent":
            initial_state["intent"] = "code_intelligence"
        elif agent_mode == "coding_agent":
            initial_state["intent"] = "generate_patch"
        elif agent_mode == "testing_agent":
            initial_state["intent"] = "run_tests"
        elif agent_mode == "validation_agent":
            initial_state["intent"] = "validate"
        
        try:
            single_result = await node_func(initial_state)
            duration_ms = int((time.monotonic() - start_time) * 1000)
            
            # Build result from single node output
            response = single_result.get("final_response") or "No response generated."
            
            return RunResult(
                session_id=session_id,
                intent=agent_mode,
                workflow="single_agent",
                plan=[],
                response=response,
                response_type="text",
                total_tokens=single_result.get("total_tokens", 0) or 0,
                duration_ms=duration_ms,
                agent_steps=single_result.get("agent_steps", []) or [],
                error=single_result.get("error"),
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"Single agent execution failed: {exc}"
            logger.exception(error_msg)
            return RunResult(
                session_id=session_id,
                intent=None,
                workflow=None,
                plan=[],
                response=f"Agent {agent_mode} execution failed: {exc}",
                response_type="text",
                total_tokens=0,
                duration_ms=duration_ms,
                agent_steps=[],
                error=error_msg,
            )

    # ── 4. Run the graph ────────────────────────────────────────────────────────
    graph_config = {"recursion_limit": 25}
    if config:
        graph_config.update(config)

    try:
        logger.info(
            f"Graph run starting | session={session_id} "
            f"project={project_id} "
            f"message_preview={user_message[:60]!r}"
        )
        final_state: GraphState = await compiled_graph.ainvoke(
            initial_state,
            config=graph_config,
        )
        logger.info(
            f"Graph run complete | session={session_id} "
            f"workflow={final_state.get('workflow')} "
            f"tokens={final_state.get('total_tokens', 0)}"
        )

    except Exception as exc:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        error_msg = f"Graph execution failed: {exc}"
        logger.exception(error_msg)
        return RunResult(
            session_id=session_id,
            intent=None,
            workflow=None,
            plan=[],
            response=(
                "The AI system encountered an internal error. "
                "Please try again or contact support."
            ),
            response_type="text",
            total_tokens=0,
            duration_ms=duration_ms,
            agent_steps=[],
            error=error_msg,
        )

    duration_ms = int((time.monotonic() - start_time) * 1000)

    # ── 5. Extract results from final state ────────────────────────────────────
    final_response = final_state.get("final_response") or "No response generated."
    response_type = final_state.get("response_type") or "text"
    intent = final_state.get("intent")
    workflow = final_state.get("workflow")
    plan = final_state.get("plan") or []
    agent_steps = final_state.get("agent_steps") or []
    total_tokens = final_state.get("total_tokens") or 0
    error = final_state.get("error")
    code_modification = final_state.get("code_modification")

    # ── 6. Persist assistant message ───────────────────────────────────────────
    assistant_message_id: Optional[str] = None
    try:
        assistant_msg = msg_service.add_message(
            session_id=session_id,
            role="assistant",
            content=final_response,
            metadata={
                "intent": intent,
                "workflow": workflow,
                "response_type": response_type,
                "total_tokens": total_tokens,
                "duration_ms": duration_ms,
            },
        )
        assistant_message_id = assistant_msg.get("id")
    except Exception as exc:
        logger.warning(f"Failed to persist assistant message: {exc}")

    # ── 7. Persist agent trace ─────────────────────────────────────────────────
    try:
        trace_service.save_trace(
            session_id=session_id,
            message_id=assistant_message_id,
            workflow=workflow or "unknown",
            steps=list(agent_steps),
            total_tokens=total_tokens,
            duration_ms=duration_ms,
        )
    except Exception as exc:
        logger.warning(f"Failed to persist agent trace: {exc}")

    # ── 8. Update session title on first turn ──────────────────────────────────
    try:
        if len(messages) <= 1:
            # First turn — auto-title the session from the intent
            title = (
                intent[:60] if intent and len(intent) > 3
                else user_message[:60]
            )
            session_service.update_session_title(session_id, title)
    except Exception as exc:
        logger.debug(f"Non-critical: failed to update session title: {exc}")

    # ── Broadcast to WebSocket clients ─────────────────────────────────────────
    # Note: This requires the app to have websocket_active_connections in app.state
    # The actual broadcasting is done by the WebSocket route in main.py
    # For now, just log for debugging
    logger.info(
        f"Chat completed | session={session_id} "
        f"agent_steps={len(agent_steps)} "
        f"response_length={len(final_response)}"
    )

    return RunResult(
        session_id=session_id,
        intent=intent,
        workflow=workflow,
        plan=plan,
        response=final_response,
        response_type=response_type,
        total_tokens=total_tokens,
        duration_ms=duration_ms,
        agent_steps=agent_steps,
        error=error,
        code_modification=code_modification,
    )
