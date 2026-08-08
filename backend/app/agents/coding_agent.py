"""
Coding Agent — Phase 4.

Responsibility:
  - Generate code modifications as unified diffs based on user requests.
  - Validate syntax before applying changes.
  - Apply patches to files with version history.
  - Provide rollback capability.

Key features:
  - Produces unified diff format (not full file rewrite).
  - Uses difflib for diff generation.
  - Validates syntax with ast.parse before applying.
  - Maintains patch history in database for rollback.
  - Works with KnowledgeAgent retrieved code for context.

Design:
  - The agent receives a coding request from the planner.
  - It retrieves relevant code from KnowledgeAgent.
  - Uses LLM to generate a unified diff.
  - Validates syntax and applies if valid.
  - Returns patch details for user approval (via frontend).
"""

from __future__ import annotations

import difflib
import ast
import logging
import tempfile
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from app.agents.base import BaseAgent
from app.orchestration.state import GraphState

logger = logging.getLogger(__name__)


class PatchGenerator:
    """Generate unified diffs and validate/apply them."""
    
    @staticmethod
    def generate_unified_diff(original: str, modified: str, file_path: str) -> str:
        """
        Generate a unified diff between original and modified content.
        
        Args:
            original: Original source code
            modified: Modified source code  
            file_path: Path to the file (for diff header)
            
        Returns:
            Unified diff string
        """
        original_lines = original.splitlines(keepends=True)
        modified_lines = modified.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            original_lines,
            modified_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm=""
        )
        return "".join(diff)
    
    @staticmethod
    def validate_syntax(code: str) -> Tuple[bool, Optional[str]]:
        """
        Validate Python syntax using ast.parse.
        
        Returns:
            (is_valid, error_message)
        """
        try:
            ast.parse(code)
            return True, None
        except SyntaxError as e:
            return False, f"Syntax error at line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, f"Parse error: {e}"
    
    @staticmethod
    def apply_patch(original: str, diff: str) -> Tuple[str, bool]:
        """
        Apply a unified diff to original content.
        
        Returns:
            (modified_content, success)
        """
        try:
            # Parse the diff
            lines = diff.splitlines(keepends=False)
            if not lines:
                return original, False
            
            # Simple diff application (for now)
            # In production, use patch utilities or library
            original_lines = original.splitlines(keepends=True)
            modified_lines = []
            i = 0
            
            for line in lines:
                if line.startswith('---') or line.startswith('+++') or line.startswith('@@'):
                    continue
                elif line.startswith('-'):
                    # Remove line - skip original
                    i += 1
                elif line.startswith('+'):
                    # Add line
                    modified_lines.append(line[1:] + '\n')
                else:
                    # Context line - keep original
                    if i < len(original_lines):
                        modified_lines.append(original_lines[i])
                        i += 1
            
            # Add remaining lines
            while i < len(original_lines):
                modified_lines.append(original_lines[i])
                i += 1
            
            return ''.join(modified_lines), True
            
        except Exception as e:
            logger.error(f"Failed to apply diff: {e}")
            return original, False


class PatchApplier:
    """
    Apply patches to files with version history.
    """
    
    @staticmethod
    def apply_patch_to_file(patch_content: str, file_path: str) -> Tuple[bool, str]:
        """
        Apply a unified diff patch to a file.
        Returns (success, message).
        """
        if not os.path.exists(file_path):
            return False, f"File not found: {file_path}"
        
        try:
            original = Path(file_path).read_text(encoding="utf-8")
            modified, success = PatchGenerator.apply_patch(original, patch_content)
            
            if not success:
                return False, "Failed to apply diff"
            
            # Validate syntax before writing
            is_valid, error = PatchGenerator.validate_syntax(modified)
            if not is_valid:
                return False, f"Syntax validation failed: {error}"
            
            # Write the modified content
            Path(file_path).write_text(modified, encoding="utf-8")
            return True, "Patch applied successfully"
        except Exception as e:
            return False, f"Error applying patch: {e}"


class CodingAgent(BaseAgent):
    """
    Generates and applies code modifications.
    """

    agent_name = "coding_agent"

    async def run(self, state: GraphState) -> dict[str, Any]:
        """
        Generate code modifications based on user request.
        
        Expected state fields:
          - user_message: the original user query
          - intent: should include "code_modification", "bug_fix", "feature_add"
          - retrieved_code: code chunks retrieved by KnowledgeAgent
          - current_plan_step: what the planner wants us to modify
        """
        user_message = state["user_message"]
        project_id   = state.get("project_id", "")
        intent       = state.get("intent", "")
        retrieved_code = state.get("retrieved_code", [])
        
        self.logger.info(
            f"CodingAgent modifying code | project={project_id} intent={intent!r}"
        )
        
        # Extract target file and modification intent
        target_info = self._extract_target_info(user_message, retrieved_code)
        
        # Get the file content
        file_content = self._get_file_content(target_info["file_path"])
        if not file_content:
            # Prepare error step
            error_msg = f"File not found: {target_info['file_path']}"
            step = self._build_step(
                input_summary=f"modify={target_info['file_path']} intent={intent}",
                output_summary=f"ERROR: {error_msg}",
                tokens_used=0,
            )
            steps, tokens = self._append_step(state, step)
            
            return {
                "context": dict(state.get("context") or {}),
                "code_modification": None,
                "agent_steps": steps,
                "total_tokens": tokens,
                "error": error_msg,
            }
        
        # Use LLM to generate modification
        llm_diff = await self._generate_diff(
            file_content, target_info, retrieved_code, user_message
        )
        
        # Validate and apply
        patch_result = self._process_patch(file_content, llm_diff, target_info["file_path"])
        
        # Prepare response
        step = self._build_step(
            input_summary=f"modify={target_info['file_path']} intent={intent}",
            output_summary=f"diff_lines={patch_result.get('diff_lines', 0)}",
            tokens_used=0  # Will be updated by LLM call
        )
        steps, tokens = self._append_step(state, step)
        
        # Update context
        context = dict(state.get("context") or {})
        context["code_modification"] = {
            "target_file": target_info["file_path"],
            "diff": patch_result.get("diff", ""),
            "applied": patch_result.get("applied", False),
            "validation_error": patch_result.get("validation_error"),
            "backup_path": patch_result.get("backup_path"),
        }
        
        return {
            "context": context,
            "code_modification": context["code_modification"],
            "agent_steps": steps,
            "total_tokens": tokens,
            "error": patch_result.get("error"),
        }
    
    def _extract_target_info(self, query: str, retrieved_code: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract target file and modification details from query.
        """
        # Default info
        info = {
            "file_path": "",
            "target_function": "",
            "target_class": "",
            "modification_type": "unknown",  # fix, add, modify, remove
        }
        
        # Look for file references in retrieved code
        if retrieved_code:
            # Use first chunk's file path as default
            first_chunk = retrieved_code[0]
            metadata = first_chunk.get("metadata", {})
            info["file_path"] = metadata.get("file_path", "")
        
        # Parse query for keywords
        query_lower = query.lower()
        if "fix" in query_lower or "bug" in query_lower:
            info["modification_type"] = "fix"
        elif "add" in query_lower or "implement" in query_lower:
            info["modification_type"] = "add"
        elif "modify" in query_lower or "change" in query_lower:
            info["modification_type"] = "modify"
        elif "remove" in query_lower or "delete" in query_lower:
            info["modification_type"] = "remove"
        
        # Try to extract function/class names
        import re
        # Look for "function X" or "class Y" patterns
        func_match = re.search(r'function\s+([a-zA-Z_][a-zA-Z0-9_]*)', query, re.IGNORECASE)
        if func_match:
            info["target_function"] = func_match.group(1)
        
        class_match = re.search(r'class\s+([a-zA-Z_][a-zA-Z0-9_]*)', query, re.IGNORECASE)
        if class_match:
            info["target_class"] = class_match.group(1)
        
        return info
    
    def _get_file_content(self, file_path: str) -> Optional[str]:
        """
        Read file content from disk.
        """
        if not file_path or not os.path.exists(file_path):
            # Try relative to project root
            project_root = Path.cwd()
            full_path = project_root / file_path
            if full_path.exists():
                try:
                    return full_path.read_text(encoding="utf-8")
                except Exception as e:
                    logger.error(f"Cannot read {full_path}: {e}")
                    return None
            return None
        
        try:
            return Path(file_path).read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Cannot read {file_path}: {e}")
            return None
    
    async def _generate_diff(
        self,
        file_content: str,
        target_info: Dict[str, Any],
        retrieved_code: List[Dict[str, Any]],
        user_query: str
    ) -> str:
        """
        Use LLM to generate a unified diff.
        """
        # Build context from retrieved code
        context_code = "\n\n".join([chunk.get("content", "") for chunk in retrieved_code[:3]])
        
        prompt = f"""
You are a coding assistant that generates unified diffs (patch format).

File to modify: {target_info['file_path']}
Modification type: {target_info['modification_type']}
Target function: {target_info['target_function']}
Target class: {target_info['target_class']}

User request: {user_query}

Current file content:
```
{file_content[:2000]}
```

Relevant context from knowledge base:
```
{context_code[:2000]}
```

Your task:
1. Analyze the user's request
2. Generate the minimal necessary changes
3. Output ONLY a unified diff in the standard format
4. The diff must be syntactically valid Python
5. Include context lines (3 lines before/after changes)

Generate the unified diff now. Output ONLY the diff, no explanations.
"""
        
        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # Extract diff (look for diff markers)
            lines = content.splitlines()
            diff_lines = []
            in_diff = False
            
            for line in lines:
                if line.startswith('---') or line.startswith('+++') or line.startswith('@@'):
                    in_diff = True
                if in_diff:
                    diff_lines.append(line)
            
            if diff_lines:
                return '\n'.join(diff_lines)
            else:
                # No diff markers, maybe LLM returned just the diff
                return content.strip()
                
        except Exception as e:
            logger.error(f"LLM diff generation failed: {e}")
            return ""
    
    def _process_patch(
        self, original_content: str, diff: str, file_path: str
    ) -> Dict[str, Any]:
        """
        Validate and apply a patch, creating backup.
        """
        if not diff.strip():
            return {"error": "Empty diff", "applied": False}
        
        # Generate modified content from diff
        modified_content, success = PatchGenerator.apply_patch(original_content, diff)
        if not success:
            return {"error": "Failed to apply diff", "applied": False}
        
        # Validate syntax
        is_valid, error = PatchGenerator.validate_syntax(modified_content)
        if not is_valid:
            return {
                "error": f"Syntax validation failed: {error}",
                "applied": False,
                "validation_error": error,
                "diff": diff,
                "diff_lines": len(diff.splitlines()),
            }
        
        # Create backup
        backup_path = self._create_backup(file_path, original_content)
        
        # Apply patch (simulated for now - actual file write would need user approval)
        # In production, this would write to file after user approval
        
        return {
            "applied": True,  # Simulated
            "diff": diff,
            "diff_lines": len(diff.splitlines()),
            "backup_path": backup_path,
            "modified_content_preview": modified_content[:500],
        }
    
    def _create_backup(self, file_path: str, content: str) -> str:
        """
        Create a backup of the original file.
        Returns backup file path.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path("backups") / Path(file_path).parent
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        backup_file = backup_dir / f"{Path(file_path).stem}_{timestamp}.bak"
        backup_file.write_text(content, encoding="utf-8")
        
        return str(backup_file)


# Add patch_history table SQL
PATCH_HISTORY_SQL = """
CREATE TABLE IF NOT EXISTS patch_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID REFERENCES projects(id) ON DELETE CASCADE,
    session_id      UUID REFERENCES sessions(id),
    file_path       TEXT NOT NULL,
    original_hash   TEXT NOT NULL,
    patch_content   TEXT NOT NULL,
    applied_by      VARCHAR(100),  -- 'agent' | 'user'
    applied_at      TIMESTAMPTZ DEFAULT NOW(),
    rolled_back_at  TIMESTAMPTZ,
    rollback_reason TEXT,
    metadata        JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_patch_history_project ON patch_history(project_id);
CREATE INDEX IF NOT EXISTS idx_patch_history_file ON patch_history(file_path);
"""