"""
Router Agent.

Responsibility:
  - Analyse the user message + recent conversation context.
  - Classify intent into a known category.
  - Select the appropriate workflow.
  - Does NOT solve the task — purely classification.

Output written to GraphState:
  intent, workflow, confidence

Workflow catalogue (extensible — add new entries as phases are built):
  code_explanation   → User wants code explained / understood
  code_debugging     → User wants a bug investigated / fixed
  code_modification  → User wants code changed / refactored
  code_generation    → User wants new code written
  documentation      → User wants docs generated
  project_planning   → User wants task breakdown / planning
  knowledge_search   → User wants to search project knowledge
  general            → Catch-all for unclear requests

Prompt design:
  - System prompt gives the agent a strict JSON contract to follow.
  - We ask for confidence so the graph can route low-confidence results
    to a clarification step in future phases.
  - Temperature is already low (set in provider config), making output
    more deterministic for classification tasks.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent
from app.models.llm_providers import LLMMessage
from app.orchestration.state import GraphState

logger = logging.getLogger(__name__)

# ── Supported workflows ────────────────────────────────────────────────────────

SUPPORTED_WORKFLOWS = [
    "code_explanation",
    "code_debugging",
    "code_modification",
    "code_generation",
    "documentation",
    "project_planning",
    "knowledge_search",
    "general",
]

# ── System prompt ──────────────────────────────────────────────────────────────

ROUTER_SYSTEM_PROMPT = """You are the Router Agent of an AI software engineering system.

Your ONLY job is to analyse the user's message and classify it into exactly one workflow.

Available workflows:
- code_explanation   : User wants to understand existing code, architecture, or a specific module.
- code_debugging     : User wants to find, investigate, or fix a bug or error.
- code_modification  : User wants to refactor, improve, or change existing code.
- code_generation    : User wants new code, a new feature, or a new file written.
- documentation      : User wants documentation, README, or API docs generated.
- project_planning   : User wants task breakdown, sprint planning, or feature roadmap.
- knowledge_search   : User wants to search for something in the project knowledge base.
- general            : The request does not clearly fit any category above.

You MUST respond with valid JSON only — no explanation, no markdown, no code fences.

Response format:
{
  "intent": "<short verb phrase describing what the user wants, max 8 words>",
  "workflow": "<one of the workflow names above>",
  "confidence": <float between 0.0 and 1.0>,
  "reasoning": "<one sentence explaining your classification>"
}"""


def _build_user_prompt(user_message: str, history_summary: str) -> str:
    parts = []
    if history_summary:
        parts.append(f"Conversation context:\n{history_summary}\n")
    parts.append(f"Current user message:\n{user_message}")
    return "\n".join(parts)


# ── Agent ──────────────────────────────────────────────────────────────────────

class RouterAgent(BaseAgent):
    agent_name = "router"

    async def run(self, state: GraphState) -> dict[str, Any]:
        user_message = state["user_message"]
        context = state.get("context") or {}
        history_summary = context.get("history_summary", "")

        self.logger.info(
            f"Router classifying | session={state['session_id']} "
            f"message_preview={user_message[:60]!r}"
        )

        messages = [
            LLMMessage("system", ROUTER_SYSTEM_PROMPT),
            LLMMessage("user", _build_user_prompt(user_message, history_summary)),
        ]

        try:
            response = await self._call_llm(messages)
            parsed = response.as_json()

            intent = parsed.get("intent", "unknown request")
            workflow = parsed.get("workflow", "general")
            confidence = float(parsed.get("confidence", 0.5))
            reasoning = parsed.get("reasoning", "")

            # Guard: reject unknown workflow names
            if workflow not in SUPPORTED_WORKFLOWS:
                self.logger.warning(
                    f"Router returned unknown workflow {workflow!r}, "
                    "falling back to 'general'"
                )
                workflow = "general"
                confidence = 0.3

            self.logger.info(
                f"Router decision | intent={intent!r} workflow={workflow} "
                f"confidence={confidence:.2f} reason={reasoning!r}"
            )

            step = self._build_step(
                input_summary=f"message: {user_message[:80]}",
                output_summary=f"intent={intent!r} workflow={workflow} confidence={confidence:.2f}",
                tokens_used=response.total_tokens,
            )
            steps, tokens = self._append_step(state, step)

            return {
                "intent": intent,
                "workflow": workflow,
                "confidence": confidence,
                "agent_steps": steps,
                "total_tokens": tokens,
            }

        except Exception as exc:
            return self._error_state(
                state,
                error_msg=f"Router agent failed: {exc}",
                agent_input=user_message[:120],
            )
