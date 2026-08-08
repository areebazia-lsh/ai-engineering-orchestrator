"""
Knowledge Agent — Phase 2.

Responsibility:
  - Receive a search query extracted from the user's request.
  - Embed the query (locally, no LLM).
  - Query the vector store for the top-k most relevant chunks.
  - Return structured results that the Response Generator uses as context.

What this agent does NOT do:
  - It does NOT interpret results — that is the Response Generator's job.
  - It does NOT call the LLM for retrieval — embeddings are pure ONNX inference.
  - It does NOT modify state outside its designated fields.

Output written to GraphState:
  retrieved_code  — list of matching code chunks (from code_knowledge collection)
  retrieved_docs  — list of matching doc chunks  (from documentation_knowledge)

Each result dict shape:
  {
    "chunk_id":    str,
    "content":     str,      # raw source/doc text shown to Response Generator
    "similarity":  float,    # 0.0–1.0
    "metadata":    dict,     # file_path, chunk_type, function_name, class_name, etc.
  }
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent
from app.ingestion.embedder import embed_single
from app.knowledge.vector_store.supabase_store import (
    SupabaseVectorStore,
    COLLECTION_CODE,
    COLLECTION_DOCS,
)
from app.orchestration.state import GraphState

logger = logging.getLogger(__name__)

# How many results to pull per collection
TOP_K_CODE = 6
TOP_K_DOCS = 4
SIMILARITY_THRESHOLD = 0.30   # cosine similarity floor — discard noise


class KnowledgeAgent(BaseAgent):
    """
    Retrieves relevant code and documentation chunks from the vector store.
    Requires a SupabaseVectorStore injected at construction time.
    Inherits BaseAgent for the trace/step helpers, but LLM is only used
    for the optional query-rewriting step — retrieval itself is LLM-free.
    """

    agent_name = "knowledge_agent"

    def __init__(self, llm, vector_store: SupabaseVectorStore) -> None:
        super().__init__(llm)
        self._store = vector_store

    async def run(self, state: GraphState) -> dict[str, Any]:
        user_message = state["user_message"]
        project_id   = state.get("project_id", "")
        intent       = state.get("intent", "")

        self.logger.info(
            f"KnowledgeAgent retrieving | session={state['session_id']} "
            f"project={project_id} intent={intent!r}"
        )

        # Build a focused search query from intent + message
        query = _build_query(user_message, intent)

        # Embed query locally — zero LLM tokens spent
        query_embedding = embed_single(query)

        retrieved_code: list[dict[str, Any]] = []
        retrieved_docs: list[dict[str, Any]] = []

        if not query_embedding:
            self.logger.warning("Empty query embedding — skipping vector search")
        else:
            # Search code knowledge
            code_results = self._store.similarity_search(
                query_embedding=query_embedding,
                collection=COLLECTION_CODE,
                project_id=project_id or None,
                top_k=TOP_K_CODE,
                similarity_threshold=SIMILARITY_THRESHOLD,
            )
            retrieved_code = _format_results(code_results)

            # Search documentation knowledge
            doc_results = self._store.similarity_search(
                query_embedding=query_embedding,
                collection=COLLECTION_DOCS,
                project_id=project_id or None,
                top_k=TOP_K_DOCS,
                similarity_threshold=SIMILARITY_THRESHOLD,
            )
            retrieved_docs = _format_results(doc_results)

        self.logger.info(
            f"Retrieved | code_chunks={len(retrieved_code)} "
            f"doc_chunks={len(retrieved_docs)}"
        )

        step = self._build_step(
            input_summary=f"query={query!r:.80} project={project_id}",
            output_summary=(
                f"code={len(retrieved_code)} chunks, "
                f"docs={len(retrieved_docs)} chunks"
            ),
            tokens_used=0,   # no LLM tokens used
        )
        steps, tokens = self._append_step(state, step)

        # Inject into context dict so Response Generator can read them
        context = dict(state.get("context") or {})
        context["retrieved_code"] = retrieved_code
        context["retrieved_docs"] = retrieved_docs

        return {
            "context":        context,
            "retrieved_code": retrieved_code,
            "retrieved_docs": retrieved_docs,
            "agent_steps":    steps,
            "total_tokens":   tokens,
        }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_query(user_message: str, intent: str) -> str:
    """
    Combine intent and message into a single focused search query.
    Keeping this simple — the embedding model handles semantic similarity.
    """
    if intent and intent != "unknown":
        return f"{intent}: {user_message}"
    return user_message


def _format_results(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise raw pgvector RPC results into a clean list."""
    out: list[dict[str, Any]] = []
    for row in raw:
        out.append({
            "chunk_id":   row.get("chunk_id", ""),
            "content":    row.get("content", ""),
            "similarity": round(float(row.get("similarity", 0.0)), 4),
            "metadata":   row.get("metadata") or {},
        })
    return out
