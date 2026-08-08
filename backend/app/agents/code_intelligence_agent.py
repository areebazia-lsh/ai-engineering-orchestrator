"""
Code Intelligence Agent — Phase 3.

Responsibility:
  - Analyze code structure and dependencies for a given Python function/class.
  - Answer questions like:
      "What does function X depend on?"
      "Which functions call function Y?"
      "What are the parameters of class Z?"
      "Show me the inheritance hierarchy of class A."
  - Uses AST analyzer to provide factual, structural answers (no LLM guessing).

Design:
  - The agent receives a code-related question from the planner.
  - It runs AST analysis on the relevant code (either from retrieved chunks
    or by analyzing files on disk).
  - It returns structured dependency information that the Response Generator
    can format into a natural answer.

This agent DOES use the LLM, but only to interpret the query and format
the answer — the actual code analysis is purely structural.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent
from app.analysis.ast_analyzer import analyze_repository, ASTAnalyzer, ModuleInfo
from app.orchestration.state import GraphState

logger = logging.getLogger(__name__)


class CodeIntelligenceAgent(BaseAgent):
    """
    Analyzes code structure and dependencies using AST analysis.
    """

    agent_name = "code_intelligence_agent"

    async def run(self, state: GraphState) -> dict[str, Any]:
        """
        Analyze code structure based on the user's question.
        
        Expected state fields:
          - user_message: the original user query
          - intent: may include "code_analysis", "dependencies", "structure"
          - project_id: which project we're analyzing
          - retrieved_code: code chunks retrieved by KnowledgeAgent
          - current_plan_step: what the planner wants us to analyze
        """
        user_message = state["user_message"]
        project_id   = state.get("project_id", "")
        intent       = state.get("intent", "")
        retrieved_code = state.get("retrieved_code", [])
        
        self.logger.info(
            f"CodeIntelligenceAgent analyzing | project={project_id} intent={intent!r}"
        )
        
        # Extract target entity from query (function, class, or file)
        target_entity = self._extract_target_entity(user_message)
        
        # Get relevant code to analyze
        code_to_analyze = self._get_relevant_code(retrieved_code, target_entity)
        
        # Run analysis
        analysis_result: Dict[str, Any] = {}
        if code_to_analyze:
            # Write code to temporary file for analysis
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
                f.write(code_to_analyze)
                temp_path = f.name
            
            try:
                analyzer = ASTAnalyzer()
                module_info = analyzer.analyze_file(temp_path)
                
                if module_info:
                    analysis_result = self._analyze_module(module_info, target_entity)
            finally:
                import os
                try:
                    os.unlink(temp_path)
                except:
                    pass
        else:
            # If no code retrieved, we can't analyze
            analysis_result = {
                "error": "No relevant code found to analyze. The KnowledgeAgent should retrieve code first.",
                "target": target_entity
            }
        
        # Format analysis for response
        formatted_analysis = self._format_analysis(analysis_result)
        
        # Use LLM to generate a helpful answer based on the analysis
        llm_response = await self._generate_explanation(
            user_message, formatted_analysis, analysis_result
        )
        
        step = self._build_step(
            input_summary=f"query={user_message!r:.60} target={target_entity}",
            output_summary=f"analysis={formatted_analysis[:80]}...",
            tokens_used=0  # Will be updated by LLM call
        )
        steps, tokens = self._append_step(state, step)
        
        # Update context with analysis results
        context = dict(state.get("context") or {})
        context["code_analysis"] = analysis_result
        context["code_intelligence_answer"] = llm_response
        
        return {
            "context": context,
            "code_analysis": analysis_result,
            "code_intelligence_answer": llm_response,
            "agent_steps": steps,
            "total_tokens": tokens,
        }
    
    def _extract_target_entity(self, query: str) -> str:
        """
        Extract function/class name from query.
        Simple heuristic: look for patterns like "function X", "class Y", "method Z".
        """
        query_lower = query.lower()
        
        # Common patterns
        patterns = [
            ("function", "function"),
            ("class", "class"), 
            ("method", "method"),
            ("def ", "def"),
            ("what does", ""),
            ("dependencies of", ""),
            ("structure of", ""),
        ]
        
        for pattern, entity_type in patterns:
            if pattern in query_lower:
                # Try to extract the name after the pattern
                idx = query_lower.find(pattern) + len(pattern)
                rest = query[idx:].strip()
                # Take first word or quoted name
                if rest:
                    # Handle quoted names
                    if rest.startswith('"') or rest.startswith("'"):
                        quote_char = rest[0]
                        end_idx = rest.find(quote_char, 1)
                        if end_idx > 0:
                            return rest[1:end_idx]
                    # Take first "word" (alphanumeric with dots)
                    import re
                    match = re.match(r'[a-zA-Z0-9_.]+', rest)
                    if match:
                        return match.group(0)
        
        # Fallback: return empty, we'll analyze whatever code we have
        return ""
    
    def _get_relevant_code(self, retrieved_code: List[Dict[str, Any]], target: str) -> str:
        """Extract code from retrieved chunks that matches the target."""
        if not retrieved_code:
            return ""
        
        # If we have a target, look for chunks containing it
        if target:
            relevant_chunks = []
            for chunk in retrieved_code:
                content = chunk.get("content", "")
                metadata = chunk.get("metadata", {})
                
                # Check if chunk contains target
                if target in content:
                    relevant_chunks.append(content)
                # Also check metadata
                elif target == metadata.get("function_name") or target == metadata.get("class_name"):
                    relevant_chunks.append(content)
            
            if relevant_chunks:
                return "\n\n".join(relevant_chunks[:3])  # Limit to 3 chunks
        
        # Fallback: use first chunk
        if retrieved_code:
            return retrieved_code[0].get("content", "")
        
        return ""
    
    def _analyze_module(self, module_info: ModuleInfo, target: str) -> Dict[str, Any]:
        """Analyze a module and extract information about the target entity."""
        result: Dict[str, Any] = {
            "target": target,
            "found": False,
            "type": None,
            "details": {},
            "dependencies": [],
            "dependents": []
        }
        
        if not target:
            # No specific target, return general module info
            result["summary"] = {
                "file": module_info.file_path,
                "functions": len(module_info.functions),
                "classes": len(module_info.classes),
                "imports": len(module_info.imports)
            }
            return result
        
        # Look for function
        for func in module_info.functions:
            if func.name == target or f"{func.class_name}.{func.name}" == target:
                result["found"] = True
                result["type"] = "function" if not func.class_name else "method"
                result["details"] = {
                    "name": func.name,
                    "class": func.class_name,
                    "parameters": func.parameters,
                    "decorators": func.decorators,
                    "docstring": func.docstring,
                    "lines": f"{func.start_line}-{func.end_line}",
                    "calls": func.calls,
                    "attributes_accessed": func.attributes_accessed
                }
                result["dependencies"] = func.calls + func.imports
                return result
        
        # Look for class
        for cls in module_info.classes:
            if cls.name == target:
                result["found"] = True
                result["type"] = "class"
                result["details"] = {
                    "name": cls.name,
                    "bases": cls.bases,
                    "docstring": cls.docstring,
                    "lines": f"{cls.start_line}-{cls.end_line}",
                    "methods": [m.name for m in cls.methods],
                    "method_count": len(cls.methods)
                }
                # Dependencies are base classes
                result["dependencies"] = cls.bases
                return result
        
        # Target not found
        result["error"] = f"Target '{target}' not found in analyzed code"
        return result
    
    def _format_analysis(self, analysis: Dict[str, Any]) -> str:
        """Format analysis results into readable text."""
        if not analysis.get("found", False):
            if "summary" in analysis:
                summary = analysis["summary"]
                return f"Module has {summary['functions']} functions, {summary['classes']} classes, imports {summary['imports']} modules."
            else:
                return analysis.get("error", "No analysis available.")
        
        details = analysis["details"]
        entity_type = analysis["type"]
        
        lines = [f"Analysis of {entity_type} '{details['name']}':"]
        
        if entity_type in ("function", "method"):
            if details.get("class"):
                lines.append(f"  Class: {details['class']}")
            lines.append(f"  Parameters: {', '.join(details['parameters'])}")
            if details.get("decorators"):
                lines.append(f"  Decorators: {', '.join(details['decorators'])}")
            if details.get("docstring"):
                lines.append(f"  Docstring: {details['docstring'][:100]}...")
            lines.append(f"  Lines: {details['lines']}")
            if details.get("calls"):
                lines.append(f"  Calls: {', '.join(details['calls'][:10])}")
        
        elif entity_type == "class":
            if details.get("bases"):
                lines.append(f"  Inherits from: {', '.join(details['bases'])}")
            if details.get("docstring"):
                lines.append(f"  Docstring: {details['docstring'][:100]}...")
            lines.append(f"  Lines: {details['lines']}")
            lines.append(f"  Methods ({details['method_count']}): {', '.join(details['methods'][:10])}")
        
        if analysis.get("dependencies"):
            lines.append(f"  Dependencies: {', '.join(analysis['dependencies'][:10])}")
        
        return "\n".join(lines)
    
    async def _generate_explanation(
        self, query: str, analysis: str, raw_result: Dict[str, Any]
    ) -> str:
        """
        Use LLM to generate a helpful explanation based on the analysis.
        """
        prompt = f"""
You are a code intelligence assistant. The user asked: "{query}"

Here is the structural analysis of the code:
{analysis}

Based on this analysis, provide a clear, helpful answer to the user's question.
Focus on the facts from the analysis, don't make things up.
If the analysis shows the entity wasn't found, explain what we did find.
Keep the answer concise and technical.
"""
        
        try:
            response = await self.llm.ainvoke(prompt)
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            self.logger.error(f"LLM explanation failed: {e}")
            return f"Code analysis complete:\n\n{analysis}"