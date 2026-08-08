"""
Context Manager Node.

This is the FIRST node that executes in every graph run.

Responsibilities:
  1. Load conversation history from the messages list in state.
  2. Summarise long histories so they fit within the LLM context window
     without wasting tokens on stale turns.
  3. Extract the most recent messages for immediate context.
  4. Attach project metadata (future phases will add retrieved code/docs here).
  5. Write a clean `context` dict into GraphState that all downstream
     agents can read without touching raw messages directly.

Context summarisation strategy:
  - If conversation history is SHORT (<= RECENT_WINDOW messages): pass it as-is.
  - If history is LONG (> RECENT_WINDOW): summarise older turns with a light
    LLM call, keep only the RECENT_WINDOW newest messages verbatim.
  - The summary is stored in context["history_summary"].
  - This is the core of Phase 1 context engineering — no vector retrieval yet.

Design note:
  Context Manager does NOT extend BaseAgent because it is a node function,
  not an agent class. It does use the LLM for summarisation, so it receives
  the provider through the closure in nodes.py.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.models.llm_providers import BaseLLMProvider, LLMMessage
from app.orchestration.state import AgentStep, GraphState

logger = logging.getLogger(__name__)

# Keep this many recent messages verbatim (no summarisation needed)
RECENT_WINDOW = 10
# Trigger summarisation once history exceeds this count
SUMMARISE_THRESHOLD = 20

SUMMARISE_SYSTEM_PROMPT = """You are a context summariser for a software engineering AI assistant.

Given a conversation history, produce a single concise paragraph (max 150 words) that captures:
- What the developer is working on
- What has been decided or attempted so far
- Any key technical details (file names, error messages, module names)
- Current status / open questions

Be factual and technical. Do not include greetings or meta-commentary.
Output ONLY the summary paragraph — no labels, no bullet points."""


async def run_context_manager(
    state: GraphState,
    llm: BaseLLMProvider,
) -> dict[str, Any]:
    """
    Prepare context for downstream agents.
    Returns partial GraphState update: {"context": {...}, "agent_steps": [...], "total_tokens": N}
    """
    session_id = state["session_id"]
    messages: list[dict[str, Any]] = state.get("messages") or []
    tokens_used = 0

    logger.info(
        f"Context Manager | session={session_id} "
        f"history_len={len(messages)}"
    )

    # ── Split history into older + recent ────────────────────────────────────
    if len(messages) <= RECENT_WINDOW:
        recent_messages = messages
        history_summary = ""
    else:
        recent_messages = messages[-RECENT_WINDOW:]
        older_messages = messages[:-RECENT_WINDOW]

        if len(messages) > SUMMARISE_THRESHOLD:
            history_summary, tokens_used = await _summarise_history(
                older_messages, llm
            )
        else:
            # History is between RECENT_WINDOW and SUMMARISE_THRESHOLD:
            # just build a plain text summary without an LLM call
            history_summary = _format_history_as_text(older_messages)

    # ── Build context dict ────────────────────────────────────────────────────
    context: dict[str, Any] = {
        "history_summary": history_summary,
        "recent_messages": recent_messages,
        "project_info": None,      # Phase 2: populated from DB + vector store
        "retrieved_code": [],      # Phase 2: code chunks from Knowledge Agent
        "retrieved_docs": [],      # Phase 2: doc chunks from Knowledge Agent
    }

    step = AgentStep(
        agent="context_manager",
        input_summary=(
            f"history={len(messages)} messages, "
            f"recent={len(recent_messages)}, "
            f"summarised={len(messages) - len(recent_messages)}"
        ),
        output_summary=(
            f"context prepared | summary={'yes' if history_summary else 'no'} "
            f"recent_messages={len(recent_messages)}"
        ),
        tokens_used=tokens_used,
    )

    existing_steps: list[AgentStep] = state.get("agent_steps") or []
    existing_tokens: int = state.get("total_tokens") or 0

    return {
        "context": context,
        "agent_steps": existing_steps + [step],
        "total_tokens": existing_tokens + tokens_used,
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _summarise_history(
    older_messages: list[dict[str, Any]],
    llm: BaseLLMProvider,
) -> tuple[str, int]:
    """Summarise older conversation turns with a lightweight LLM call."""
    history_text = _format_history_as_text(older_messages)

    prompt_messages = [
        LLMMessage("system", SUMMARISE_SYSTEM_PROMPT),
        LLMMessage(
            "user",
            f"Conversation history to summarise:\n\n{history_text}",
        ),
    ]

    try:
        response = await llm.chat(prompt_messages)
        logger.debug(
            f"History summarised | "
            f"input_messages={len(older_messages)} "
            f"tokens={response.total_tokens}"
        )
        return response.content.strip(), response.total_tokens
    except Exception as exc:
        logger.warning(f"History summarisation failed: {exc}. Using raw text.")
        return history_text[:500] + "...", 0


def _format_history_as_text(messages: list[dict[str, Any]]) -> str:
    """Convert message dicts into a readable transcript string."""
    lines: list[str] = []
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
        else:
            # LangChain message object (HumanMessage, AIMessage, etc.)
            role = getattr(msg, "type", "unknown").upper()
            content = getattr(msg, "content", "")
        # Truncate very long individual messages
        if len(content) > 400:
            content = content[:400] + "..."
        lines.append(f"{role}: {content}")
    return "\n".join(lines)
