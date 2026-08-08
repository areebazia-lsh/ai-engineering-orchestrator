"""
Memory Service — Phase 5.

Handles long-term memory CRUD operations and context summarization.

Long-term memory is stored in the `long_term_memory` table with:
  - memory_type: preference | project_context | conversation_summary
  - key: unique identifier for the memory item
  - value: JSON-serialized memory content
  - importance: 0.0-1.0 weight for retrieval

Context summarizer reduces conversation history to ~20 messages,
then summarizes older turns into a context_summary memory item.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from datetime import datetime

from supabase import Client

logger = logging.getLogger(__name__)


MEMORY_TYPE_PREFERENCE = "preference"
MEMORY_TYPE_PROJECT_CONTEXT = "project_context"
MEMORY_TYPE_CONVERSATION_SUMMARY = "conversation_summary"


@dataclass
class MemoryItem:
    """A single long-term memory item."""
    project_id: str
    memory_type: str
    key: str
    value: Any
    importance: float = 0.5
    session_id: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "memory_type": self.memory_type,
            "key": self.key,
            "value": json.dumps(self.value) if not isinstance(self.value, str) else self.value,
            "importance": self.importance,
            "session_id": self.session_id,
        }


class MemoryService:
    """
    CRUD operations for long-term memory.
    """
    
    def __init__(self, client: Client):
        self.client = client
        self.table_name = "long_term_memory"
    
    def get_memory(
        self, project_id: str, memory_type: str, key: str
    ) -> Optional[dict]:
        """
        Retrieve a single memory item.
        """
        result = self.client.table(self.table_name).select("*").eq(
            "project_id", project_id
        ).eq("memory_type", memory_type).eq("key", key).execute()
        
        if result.data:
            item = result.data[0]
            return {
                "project_id": item["project_id"],
                "memory_type": item["memory_type"],
                "key": item["key"],
                "value": item["value"],
                "importance": item["importance"],
                "session_id": item["session_id"],
                "created_at": item["created_at"],
            }
        return None
    
    def get_all_memory(
        self, project_id: str, memory_type: Optional[str] = None
    ) -> List[dict]:
        """
        Retrieve all memory items for a project, optionally filtered by type.
        """
        query = self.client.table(self.table_name).select("*").eq(
            "project_id", project_id
        )
        
        if memory_type:
            query = query.eq("memory_type", memory_type)
        
        query = query.order("importance", desc=True)
        result = query.execute()
        
        items = []
        for item in result.data:
            items.append({
                "project_id": item["project_id"],
                "memory_type": item["memory_type"],
                "key": item["key"],
                "value": item["value"],
                "importance": item["importance"],
                "session_id": item["session_id"],
                "created_at": item["created_at"],
            })
        return items
    
    def save_memory(self, item: MemoryItem) -> dict:
        """
        Save or update a memory item (upsert).
        """
        data = item.to_dict()
        data["updated_at"] = datetime.utcnow().isoformat()
        
        result = self.client.table(self.table_name).upsert(data).execute()
        return result.data[0] if result.data else {}
    
    def delete_memory(
        self, project_id: str, memory_type: str, key: str
    ) -> bool:
        """
        Delete a memory item.
        """
        result = self.client.table(self.table_name).delete().eq(
            "project_id", project_id
        ).eq("memory_type", memory_type).eq("key", key).execute()
        return True
    
    def delete_project_memory(self, project_id: str) -> int:
        """
        Delete all memory items for a project.
        """
        result = self.client.table(self.table_name).delete().eq(
            "project_id", project_id
        ).execute()
        return len(result.data) if result.data else 0


class ContextSummarizer:
    """
    Summarize conversation history when it exceeds a threshold.
    
    Strategy:
    - Track message count per session
    - When history exceeds ~20 messages, summarize older turns
    - Store summary in long_term_memory for future context
    """
    
    def __init__(self, client: Client):
        self.client = client
        self.memory_service = MemoryService(client)
        self.summarize_threshold = 20
    
    def needs_summarization(
        self, project_id: str, session_id: str, message_count: int
    ) -> bool:
        """
        Check if we should summarize the conversation history.
        """
        # Check if we already have a recent summary
        recent_summary = self.memory_service.get_memory(
            project_id,
            MEMORY_TYPE_CONVERSATION_SUMMARY,
            f"session_{session_id}"
        )
        
        if recent_summary:
            # Don't re-summarize if we have a recent one
            return False
        
        return message_count >= self.summarize_threshold
    
    def summarize_history(
        self, messages: List[dict], project_id: str, session_id: str
    ) -> str:
        """
        Generate a summary of conversation history.
        Returns the summary text.
        """
        if not messages:
            return ""
        
        # Extract just the user and assistant messages
        conversation_lines = []
        for msg in messages[-self.summarize_threshold:]:
            if isinstance(msg, dict):
                role = msg.get("role", "")
                content = msg.get("content", "")[:500]
            else:
                role = getattr(msg, "type", "")
                content = getattr(msg, "content", "")[:500]
            if role in ("user", "assistant"):
                conversation_lines.append(f"{role}: {content}")
        
        full_conversation = "\n".join(conversation_lines)
        
        # Generate summary using LLM (would need LLM injection)
        # For now, return a placeholder
        summary = (
            f"Conversation summary for session {session_id}. "
            f"Last {min(len(messages), self.summarize_threshold)} turns covered."
        )
        
        # Save the summary to long-term memory
        self.memory_service.save_memory(MemoryItem(
            project_id=project_id,
            memory_type=MEMORY_TYPE_CONVERSATION_SUMMARY,
            key=f"session_{session_id}",
            value={
                "summary": summary,
                "message_count": len(messages),
                "saved_at": datetime.utcnow().isoformat(),
            },
            importance=0.8,
            session_id=session_id,
        ))
        
        return summary
    
    def get_context_for_planner(
        self, project_id: str, session_id: str, recent_messages: List[dict]
    ) -> dict:
        """
        Get memory context for the planner.
        Returns a dict with history_summary and any relevant preferences.
        """
        context = {
            "history_summary": "",
            "preferences": [],
        }
        
        # Get conversation summary
        summary = self.memory_service.get_memory(
            project_id,
            MEMORY_TYPE_CONVERSATION_SUMMARY,
            f"session_{session_id}"
        )
        
        if summary:
            context["history_summary"] = summary.get("value", "")
        elif len(recent_messages) >= self.summarize_threshold:
            # Trigger summarization
            summary_text = self.summarize_history(
                recent_messages, project_id, session_id
            )
            context["history_summary"] = summary_text
        
        # Get project preferences
        preferences = self.memory_service.get_all_memory(
            project_id,
            MEMORY_TYPE_PREFERENCE
        )
        context["preferences"] = [
            {"key": p["key"], "value": p["value"]}
            for p in preferences
        ]
        
        return context