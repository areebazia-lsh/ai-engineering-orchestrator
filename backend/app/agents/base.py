"""
Base agent interface.

Design decisions:
- Every agent is a class with a single public method: run(state) → dict.
  The return dict is a PARTIAL GraphState update — LangGraph merges it.
- Agents receive a BaseLLMProvider at construction time (dependency injection).
  They never import or instantiate LLM clients directly.
- _build_step() is a helper that produces a consistent AgentStep trace entry.
  Every agent must call this and include it in the returned state update so
  the orchestration layer can build a complete trace.
- _handle_llm_error() gives a single place to catch and log provider errors
  without crashing the entire graph — the node returns an error state instead,
  and the graph can route to a graceful response.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from app.models.llm_providers import BaseLLMProvider, LLMMessage, LLMResponse
from app.orchestration.state import AgentStep, GraphState

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Abstract base for all agents in the orchestration graph.

    Subclasses must implement:
        run(state: GraphState) -> dict
            Called by the LangGraph node function.
            Must return a partial GraphState dict.
    """

    # Override in subclass — used in trace entries and log output
    agent_name: str = "base_agent"

    def __init__(self, llm: BaseLLMProvider) -> None:
        self.llm = llm
        self.logger = logging.getLogger(
            f"{__name__}.{self.__class__.__name__}"
        )

    @abstractmethod
    async def run(self, state: GraphState) -> dict[str, Any]:
        """
        Execute the agent logic against the current graph state.

        Args:
            state: Full current GraphState (read-only in practice).

        Returns:
            Partial GraphState dict with only the keys this agent modifies.
            Must always include an updated `agent_steps` list and `total_tokens`.
        """
        ...

    # ── Shared helpers ─────────────────────────────────────────────────────────

    def _build_step(
        self,
        input_summary: str,
        output_summary: str,
        tokens_used: int = 0,
    ) -> AgentStep:
        """Build a trace step entry for this agent's execution."""
        return AgentStep(
            agent=self.agent_name,
            input_summary=input_summary,
            output_summary=output_summary,
            tokens_used=tokens_used,
        )

    def _append_step(
        self,
        state: GraphState,
        step: AgentStep,
    ) -> tuple[list[AgentStep], int]:
        """
        Return updated agent_steps list and total_tokens.
        Use the returned values directly in the partial state dict:

            steps, tokens = self._append_step(state, step)
            return {"agent_steps": steps, "total_tokens": tokens, ...}
        """
        existing_steps: list[AgentStep] = state.get("agent_steps", [])
        existing_tokens: int = state.get("total_tokens", 0)
        return (
            existing_steps + [step],
            existing_tokens + step["tokens_used"],
        )

    async def _call_llm(self, messages: list[LLMMessage]) -> LLMResponse:
        """
        Wrapper around llm.chat() with timing and error logging.
        Re-raises exceptions — callers handle failures in their run() method.
        """
        start = time.monotonic()
        response = await self.llm.chat(messages)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        self.logger.debug(
            f"{self.agent_name} LLM call | "
            f"model={response.model} "
            f"tokens={response.total_tokens} "
            f"duration={elapsed_ms}ms"
        )
        return response

    def _error_state(
        self,
        state: GraphState,
        error_msg: str,
        agent_input: str = "",
    ) -> dict[str, Any]:
        """
        Return a partial state that marks an error without crashing the graph.
        The response generator will surface this gracefully to the user.
        """
        self.logger.error(f"{self.agent_name} error: {error_msg}")
        step = self._build_step(
            input_summary=agent_input,
            output_summary=f"ERROR: {error_msg}",
            tokens_used=0,
        )
        steps, tokens = self._append_step(state, step)
        return {
            "error": error_msg,
            "agent_steps": steps,
            "total_tokens": tokens,
        }
