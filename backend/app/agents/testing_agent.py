"""
Testing Agent — Phase 6.

Responsibility:
  - Generate pytest tests for functions/classes based on user requests.
  - Execute tests in a sandboxed environment (subprocess with timeout).
  - Analyze test results (pass/fail/timeout).
  - Return structured results to be validated.

Key features:
  - Generates pytest tests using LLM based on function signature and docstring.
  - Runs tests in subprocess with timeout to prevent hangs.
  - Captures stdout/stderr for debugging.
  - Parses pytest output into structured pass/fail status.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.agents.base import BaseAgent
from app.orchestration.state import GraphState

logger = logging.getLogger(__name__)


class TestGenerator:
    """
    Generate pytest test cases for Python functions/classes.
    """
    
    @staticmethod
    def generate_test(
        function_name: str,
        file_path: str,
        function_signature: str,
        docstring: Optional[str],
        context_code: str,
        user_request: str
    ) -> str:
        """
        Generate a pytest test for a function.
        """
        prompt = f"""
You are a test generation assistant.

Function to test:
  File: {file_path}
  Name: {function_name}
  Signature: {function_signature}
  Docstring: {docstring or 'None'}

Surrounding code context:
```
{context_code}
```

User request: {user_request}

Your task:
1. Analyze the function signature and docstring
2. Generate a comprehensive pytest test that validates the function's behavior
3. Include edge cases if the function has any obvious ones
4. Use realistic test data
5. Include assertions for expected behavior

Output ONLY the test code, nothing else. No markdown fences, no explanations.

The test should follow pytest conventions:
- Use pytest.raises() for expected exceptions
- Use parametrize for multiple test cases
- Use fixtures for setup/teardown
- Keep tests focused on one behavior per test

Test code:
"""
        
        return prompt


class TestRunner:
    """
    Run pytest tests in a sandboxed environment.
    """
    
    @staticmethod
    def run_tests(
        test_code: str,
        timeout: int = 30
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Run pytest tests and return (success, results).
        
        Returns:
            (success, results) where results contains:
              - exit_code: process exit code
              - stdout: captured stdout
              - stderr: captured stderr
              - passed: number of passed tests
              - failed: number of failed tests
        """
        # Write test to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(test_code)
            test_file = f.name
        
        try:
            # Run pytest with timeout
            result = subprocess.run(
                ["python", "-m", "pytest", test_file, "-v"],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=os.getcwd()
            )
            
            # Parse pytest output
            passed = result.stdout.count(" PASSED ")
            failed = result.stdout.count(" FAILED ")
            
            # Also check stderr for errors
            if result.stderr:
                passed += result.stderr.count(" PASSED ")
                failed += result.stderr.count(" FAILED ")
            
            return result.returncode == 0, {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "passed": passed,
                "failed": failed,
            }
            
        except subprocess.TimeoutExpired:
            return False, {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Test execution timed out after {timeout} seconds",
                "passed": 0,
                "failed": 0,
                "timeout": True,
            }
        finally:
            try:
                os.unlink(test_file)
            except:
                pass


class TestingAgent(BaseAgent):
    """
    Generates and runs tests for Python code.
    """

    agent_name = "testing_agent"

    async def run(self, state: GraphState) -> dict[str, Any]:
        """
        Generate and run tests for the target function/class.
        
        Expected state fields:
          - user_message: the original user request
          - intent: should include "test", "add_test", "write_test"
          - retrieved_code: code chunks with target function
          - current_plan_step: what to test
        """
        user_message = state["user_message"]
        project_id   = state.get("project_id", "")
        intent       = state.get("intent", "")
        
        self.logger.info(
            f"TestingAgent generating tests | project={project_id} intent={intent!r}"
        )
        
        # Extract target info from retrieved code
        retrieved_code = state.get("retrieved_code", [])
        target_info = self._extract_target_info(retrieved_code)
        
        if not target_info:
            return {
                "context": dict(state.get("context") or {}),
                "agent_steps": state.get("agent_steps") or [],
                "total_tokens": state.get("total_tokens") or 0,
                "error": "No target function/class found to test",
            }
        
        # Generate test code
        test_code = await self._generate_test_code(target_info, user_message)
        
        if not test_code:
            return {
                "context": dict(state.get("context") or {}),
                "agent_steps": state.get("agent_steps") or [],
                "total_tokens": state.get("total_tokens") or 0,
                "error": "Failed to generate test code",
            }
        
        # Run tests
        success, results = TestRunner.run_tests(test_code)
        
        # Prepare response
        step = self._build_step(
            input_summary=f"test={target_info['name']} request={intent}",
            output_summary=f"passed={results.get('passed', 0)} failed={results.get('failed', 0)}",
            tokens_used=0
        )
        steps, tokens = self._append_step(state, step)
        
        # Update context
        context = dict(state.get("context") or {})
        context["test_generation"] = {
            "target": target_info,
            "test_code": test_code,
            "results": results,
            "success": success,
        }
        
        return {
            "context": context,
            "test_generation": context["test_generation"],
            "agent_steps": steps,
            "total_tokens": tokens,
            "error": None if success else "Tests failed or timed out",
        }
    
    def _extract_target_info(self, retrieved_code: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Extract target function/class info from retrieved code.
        """
        if not retrieved_code:
            return None
        
        first_chunk = retrieved_code[0]
        metadata = first_chunk.get("metadata", {})
        
        return {
            "name": metadata.get("function_name") or metadata.get("class_name", "unknown"),
            "file_path": metadata.get("file_path", ""),
            "chunk_type": metadata.get("chunk_type", "unknown"),
            "content": first_chunk.get("content", ""),
        }
    
    async def _generate_test_code(
        self, target_info: Dict[str, Any], user_request: str
    ) -> str:
        """
        Generate pytest test code for the target.
        """
        prompt = TestGenerator.generate_test(
            function_name=target_info["name"],
            file_path=target_info["file_path"],
            function_signature=target_info["name"],
            docstring="Test the " + target_info["name"] + " function.",
            context_code=target_info["content"][:1000],
            user_request=user_request
        )
        
        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # Extract test code (strip markdown fences if present)
            if content.startswith("```"):
                lines = content.splitlines()
                if lines[0].startswith("```"):
                    # Find closing fence
                    end_idx = -1
                    for i, line in enumerate(lines[1:], 1):
                        if line.strip() == "```":
                            end_idx = i
                            break
                    if end_idx > 0:
                        content = "\n".join(lines[1:end_idx])
            
            return content.strip()
            
        except Exception as e:
            logger.error(f"Test generation failed: {e}")
            return ""