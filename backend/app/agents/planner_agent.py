"""
Planner Agent.

Responsibility:
  - Convert the user's high-level goal into an ordered execution plan.
  - Each plan step specifies what sub-agent or capability to invoke next.
  - The planner is the "reasoning brain" — future phases will route to
    other agents (Knowledge, CodeIntel, Coding, Testing) based on this plan.

Output written to GraphState:
  plan: list of step dictionaries

Plan step structure:
{
  "step": 1,
  "type": "<action_type>",
  "description": "<what this step accomplishes>",
  "params": {...}  # optional parameters
}

Step types (Phase 1 — only 'respond' is implemented, rest are placeholders):
  - retrieve_knowledge   → Query vector DB (future phase)
  - analyze_code         → AST / dependency analysis (future phase)
  - generate_patch       → Create code modification (future phase)
  - run_tests            → Execute test suite (future phase)
  - validate             → Check correctness (future phase)
  - respond              → Synthesize final answer (Phase 1 — works now)

In Phase 1, all plans end with a single 'respond' step since we haven't built
retrieval, analysis, or modification yet. Future phases will expand this.

Prompt design:
  - System prompt describes the planning role and available actions.
  - User prompt includes intent, workflow, and conversation context.
  - LLM outputs a JSON array of steps.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent
from app.models.llm_providers import LLMMessage
from app.orchestration.state import GraphState

logger = logging.getLogger(__name__)

# ── System prompt ──────────────────────────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = """You are the Planner Agent of an AI software engineering system.

Your role:
  - Convert the user's request into a clear, step-by-step execution plan.
  - Each step specifies ONE action type from the list below.
  - The plan is executed sequentially by other specialized agents.

Available step types:
  - retrieve_knowledge : Search the project knowledge base (code, docs, bugs).
                         Use this whenever the user asks about existing code,
                         functions, classes, architecture, or project specifics.
                         This step is FULLY IMPLEMENTED — always use it for code questions.
  - code_intelligence  : Deep AST/dependency analysis (Phase 3 — FULLY IMPLEMENTED).
                         Use this when the user asks about code structure, dependencies,
                         function signatures, class hierarchies, imports, or call graphs.
                         This step requires retrieve_knowledge to run first to get code.
  - generate_patch     : Generate code changes as a unified diff (Phase 4 — FULLY IMPLEMENTED).
                         Use this when the user requests code modifications, bug fixes,
                         feature additions, or any code changes.
                         This step should follow retrieve_knowledge to get context.
  - run_tests          : Execute automated tests (Phase 6 — FULLY IMPLEMENTED).
                         Use this when the user requests tests to be generated/running.
                         This step follows generate_patch to validate changes.
  - validate           : Check correctness (Phase 6 — FULLY IMPLEMENTED).
                         Use this to validate code patches against test results.
                         This step follows generate_patch or run_tests.
  - respond            : Synthesize the final answer for the user.
                         ALWAYS the last step. Required in every plan.

Decision rules:
  1. If the user asks about project code, functions, classes, modules, architecture,
     bugs, or any specific implementation detail → start with retrieve_knowledge.
  2. If the user asks about code structure, dependencies, function signatures,
     class inheritance, imports, or call graphs → use code_intelligence.
  3. If the user requests code modifications, bug fixes, feature additions,
     or any code changes → use generate_patch.
  4. If the user requests tests to be generated or run → use run_tests.
  5. If the user requests validation of code changes → use validate.
  6. code_intelligence and generate_patch steps should follow retrieve_knowledge steps.
  7. run_tests and validate steps should follow generate_patch steps.
  8. If the user asks a general software engineering question with no project context
     needed → use ONLY respond.
  9. If the project_ingested flag is false → use ONLY respond (no code to search).
  10. Keep plans to 1–3 steps. Never exceed 5 steps.
  11. Every plan MUST end with respond.

You MUST respond with valid JSON only — no explanation, no markdown fences.

Response format:
{
  "plan": [
    {
      "step": 1,
      "type": "<action_type>",
      "description": "<one sentence: what this step achieves>",
      "params": {}
    }
  ]
}"""


def _build_planning_prompt(state: GraphState) -> str:
    user_message = state["user_message"]
    intent       = state.get("intent", "unknown")
    workflow     = state.get("workflow", "general")
    context      = state.get("context") or {}
    memory_context = context.get("memory_context", {})
    history_summary = memory_context.get("history_summary", "")
    preferences = memory_context.get("preferences", [])

    # Tell the planner whether a project has been ingested so it knows
    # whether retrieve_knowledge will return anything useful.
    project_id = state.get("project_id", "")
    project_ingested = bool(project_id and project_id != "")

    parts: list[str] = []
    if history_summary:
        parts.append(f"Conversation context:\n{history_summary}\n")
    
    # Include preferences in context
    if preferences:
        parts.append("Project preferences:")
        for pref in preferences:
            parts.append(f"  {pref['key']}: {pref['value'][:100]}")
        parts.append("")

    parts += [
        f"User intent:       {intent}",
        f"Workflow:          {workflow}",
        f"Project ID:        {project_id or 'none'}",
        f"Project ingested:  {project_ingested}",
        f"User message:      {user_message}",
        "",
        "Create an execution plan to address this request.",
    ]
    return "\n".join(parts)






# ── Agent ──────────────────────────────────────────────────────────────────────

class PlannerAgent(BaseAgent):
    agent_name = "planner"

    async def run(self, state: GraphState) -> dict[str, Any]:
        intent = state.get("intent", "unknown")
        workflow = state.get("workflow", "general")

        self.logger.info(
            f"Planner reasoning | session={state['session_id']} "
            f"intent={intent!r} workflow={workflow}"
        )

        # Get memory context BEFORE building planning prompt
        project_id = state.get("project_id", "")
        session_id = state.get("session_id", "")
        context = state.get("context") or {}
        
        # Inject memory context into state if not already present
        if "memory_context" not in context:
            from app.memory.memory_service import ContextSummarizer, MemoryService
            from app.database.supabase_client import get_supabase_client
            
            client = get_supabase_client()
            summarizer = ContextSummarizer(client)
            
            recent_messages = []
            if "messages" in state:
                recent_messages = state["messages"]
            
            memory_context = summarizer.get_context_for_planner(
                project_id, session_id, recent_messages
            )
            context["memory_context"] = memory_context
            state["context"] = context
        
        messages = [
            LLMMessage("system", PLANNER_SYSTEM_PROMPT),
            LLMMessage("user", _build_planning_prompt(state)),
        ]

        try:
            response = await self._call_llm(messages)
            parsed = response.as_json()

            plan = parsed.get("plan", [])
            if not plan:
                # Safety fallback — if LLM returns empty, create a minimal plan
                self.logger.warning("Planner returned empty plan, adding default 'respond' step")
                plan = [
                    {
                        "step": 1,
                        "type": "respond",
                        "description": "Answer the user directly",
                        "params": {},
                    }
                ]

            # Ensure the last step is always 'respond'
            if plan and plan[-1]["type"] != "respond":
                plan.append(
                    {
                        "step": len(plan) + 1,
                        "type": "respond",
                        "description": "Provide final answer to user",
                        "params": {},
                    }
                )

            self.logger.info(
                f"Plan created | steps={len(plan)} "
                f"types={[s['type'] for s in plan]}"
            )

            step = self._build_step(
                input_summary=f"intent={intent!r} workflow={workflow}",
                output_summary=f"plan with {len(plan)} steps: {', '.join(s['type'] for s in plan)}",
                tokens_used=response.total_tokens,
            )
            steps, tokens = self._append_step(state, step)

            return {
                "plan": plan,
                "agent_steps": steps,
                "total_tokens": tokens,
            }

        except Exception as exc:
            return self._error_state(
                state,
                error_msg=f"Planner agent failed: {exc}",
                agent_input=f"intent={intent} workflow={workflow}",
            )
