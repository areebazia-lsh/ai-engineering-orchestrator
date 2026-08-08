"""
Response Generator Node.

This is the LAST node that executes in every graph run.

Responsibilities:
  1. Receive the fully populated GraphState (intent, workflow, plan, any
     retrieved context, error flags).
  2. Synthesise a clear, helpful final response for the user.
  3. Handle the error path — if a previous node set state["error"],
     produce a graceful degraded response instead of crashing.
  4. Write final_response, response_type, and the final agent_step
     into GraphState.

Response type selection:
  "text"         → General explanation or answer (most responses in Phase 1)
  "plan"         → When the user asked for planning and the plan is the output
  "patch"        → Phase 2+ — when a code patch is ready
  "test_results" → Phase 2+ — when test execution results are ready

Prompt design:
  - System prompt gives the agent its role as a senior software engineer.
  - User prompt assembles ALL relevant context: intent, plan, any retrieved
    code/docs, and the original question.
  - The LLM writes the final answer in plain text (not JSON) — this is the
    only agent where we want natural language output, not structured data.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent
from app.models.llm_providers import LLMMessage
from app.orchestration.state import GraphState

logger = logging.getLogger(__name__)

# ── System prompt ──────────────────────────────────────────────────────────────

RESPONSE_GENERATOR_SYSTEM_PROMPT = """You are a senior software engineering AI assistant embedded in a software house.

Your role is to provide clear, precise, and technically accurate responses to software engineering questions.

Guidelines:
- Be direct and concise. Engineers are busy — avoid filler.
- Use code blocks (``` language) whenever you include code examples.
- If explaining architecture, use simple ASCII diagrams if helpful.
- If the plan includes steps that weren't executed yet (they're placeholders), be honest:
  say what you know and what would require deeper analysis in a future step.
- Always be technically specific — mention actual file names, function names,
  module names, or error patterns when they're available in the context.
- If you don't have enough information, say so clearly and explain what
  additional context would help.

Tone: professional, collaborative, not patronising."""


def _build_response_prompt(state: GraphState) -> str:
    """Assemble the full context prompt for the response generator."""
    parts: list[str] = []

    user_message = state["user_message"]
    intent = state.get("intent", "")
    workflow = state.get("workflow", "general")
    plan = state.get("plan") or []
    context = state.get("context") or {}
    history_summary = context.get("history_summary", "")
    recent_messages = context.get("recent_messages") or []
    error = state.get("error")

    # ── Error path ────────────────────────────────────────────────────────────
    if error:
        return (
            f"The system encountered an error while processing the request.\n"
            f"Error: {error}\n\n"
            f"Original user request: {user_message}\n\n"
            f"Please provide a helpful response explaining the limitation "
            f"and suggest what the user can try instead."
        )

    # ── Normal path ───────────────────────────────────────────────────────────
    if history_summary:
        parts.append(f"## Conversation Context\n{history_summary}")

    if recent_messages:
        recent_transcript = _format_recent(recent_messages)
        parts.append(f"## Recent Conversation\n{recent_transcript}")

    parts.append(f"## Current Request\n{user_message}")

    if intent:
        parts.append(f"## Classified Intent\n{intent} (workflow: {workflow})")

    if plan:
        plan_text = _format_plan(plan)
        parts.append(f"## Execution Plan\n{plan_text}")

    # Phase 2+: retrieved_code and retrieved_docs will be injected here
    retrieved_code = context.get("retrieved_code") or []
    if retrieved_code:
        parts.append(
            f"## Retrieved Code Snippets\n"
            + "\n\n".join(
                f"**{c.get('file_path', 'unknown')}**\n```{c.get('language', '')}\n{c.get('content', '')}\n```"
                for c in retrieved_code[:3]  # cap at 3 to save tokens
            )
        )

    retrieved_docs = context.get("retrieved_docs") or []
    if retrieved_docs:
        parts.append(
            f"## Retrieved Documentation\n"
            + "\n\n".join(
                f"**{d.get('source', 'unknown')}**\n{d.get('content', '')}"
                for d in retrieved_docs[:2]
            )
        )

    parts.append(
        "\nUsing all of the above context, provide a thorough, technically accurate response "
        "to the user's request."
    )

    return "\n\n".join(parts)


def _format_plan(plan: list[dict[str, Any]]) -> str:
    lines = []
    for step in plan:
        lines.append(
            f"  {step.get('step', '?')}. [{step.get('type', '?')}] "
            f"{step.get('description', '')}"
        )
    return "\n".join(lines)


def _format_recent(messages: list[dict[str, Any]]) -> str:
    lines = []
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
        else:
            role = getattr(msg, "type", "unknown").upper()
            content = getattr(msg, "content", "")
        if len(content) > 300:
            content = content[:300] + "..."
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _determine_response_type(state: GraphState) -> str:
    """Infer what kind of response this is based on state."""
    if state.get("error"):
        return "text"
    workflow = state.get("workflow", "general")
    if workflow == "project_planning":
        return "plan"
    # Phase 2+: "patch" and "test_results" will be added
    return "text"


# ── Agent ──────────────────────────────────────────────────────────────────────

class ResponseGeneratorAgent(BaseAgent):
    agent_name = "response_generator"

    async def run(self, state: GraphState) -> dict[str, Any]:
        self.logger.info(
            f"Response Generator | session={state['session_id']} "
            f"workflow={state.get('workflow')} "
            f"error={'yes' if state.get('error') else 'no'}"
        )

        response_type = _determine_response_type(state)

        messages = [
            LLMMessage("system", RESPONSE_GENERATOR_SYSTEM_PROMPT),
            LLMMessage("user", _build_response_prompt(state)),
        ]

        try:
            response = await self._call_llm(messages)
            final_response = response.content.strip()

            self.logger.info(
                f"Response generated | "
                f"type={response_type} "
                f"length={len(final_response)} chars "
                f"tokens={response.total_tokens}"
            )

            step = self._build_step(
                input_summary=(
                    f"intent={state.get('intent')!r} "
                    f"workflow={state.get('workflow')!r} "
                    f"plan_steps={len(state.get('plan') or [])}"
                ),
                output_summary=(
                    f"response_type={response_type} "
                    f"length={len(final_response)} chars"
                ),
                tokens_used=response.total_tokens,
            )
            steps, tokens = self._append_step(state, step)

            return {
                "final_response": final_response,
                "response_type": response_type,
                "agent_steps": steps,
                "total_tokens": tokens,
            }

        except Exception as exc:
            # Last resort: even the response generator failed
            error_msg = f"Response generator failed: {exc}"
            self.logger.error(error_msg)
            step = self._build_step(
                input_summary="response synthesis",
                output_summary=f"FATAL ERROR: {error_msg}",
                tokens_used=0,
            )
            steps, tokens = self._append_step(state, step)
            return {
                "final_response": (
                    "I encountered an unexpected error while generating a response. "
                    "Please try again or check the system logs."
                ),
                "response_type": "text",
                "agent_steps": steps,
                "total_tokens": tokens,
            }
