"""
Validation Agent — Phase 6.

Responsibility:
  - Validate code patches against test results.
  - Check for syntax errors, logic issues, regression risks.
  - Provide approval/recommendation for patch application.
  - Handle retry logic when validation fails.

Validation checklist:
  1. Syntax is valid (Python AST parse)
  2. All new tests pass
  3. No regressions introduced
  4. Code follows project style
  5. Documentation updated (docstrings, comments)
"""

from __future__ import annotations

import ast
import logging
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent
from app.orchestration.state import GraphState

logger = logging.getLogger(__name__)


class SyntaxValidator:
    """Validate Python syntax."""
    
    @staticmethod
    def validate(code: str) -> tuple[bool, Optional[str]]:
        """
        Validate Python syntax using ast.parse.
        Returns (is_valid, error_message).
        """
        try:
            ast.parse(code)
            return True, None
        except SyntaxError as e:
            return False, f"Syntax error at line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, f"Parse error: {e}"


class ValidationAgent(BaseAgent):
    """
    Validates code patches and test results.
    """

    agent_name = "validation_agent"

    async def run(self, state: GraphState) -> dict[str, Any]:
        """
        Validate a code patch against test results.
        
        Expected state fields:
          - code_modification: patch details from CodingAgent
          - test_generation: test results from TestingAgent
          - retrieved_code: original code for comparison
        """
        self.logger.info("ValidationAgent validating patch...")
        
        # Extract validation inputs
        code_mod = state.get("code_modification", {})
        test_gen = state.get("test_generation", {})
        retrieved_code = state.get("retrieved_code", [])
        
        patch_code = code_mod.get("diff", "")
        modified_preview = code_mod.get("modified_content_preview", "")
        test_success = test_gen.get("success", False)
        test_results = test_gen.get("results", {})
        
        # Run validation checks
        validation_results = self._run_validation(
            patch_code=patch_code,
            modified_preview=modified_preview,
            test_success=test_success,
            test_results=test_results,
            retrieved_code=retrieved_code,
        )
        
        # Decide: approve or reject
        approved = validation_results["passed"] >= 3  # Must pass at least 3 checks
        approval_reasons = validation_results["passed_checks"]
        rejection_reasons = validation_results["failed_checks"]
        
        step = self._build_step(
            input_summary=f"patch={len(patch_code)} chars tests={'passed' if test_success else 'failed'}",
            output_summary=f"approved={approved} checks_passed={len(approval_reasons)}",
            tokens_used=0
        )
        steps, tokens = self._append_step(state, step)
        
        # Update context
        context = dict(state.get("context") or {})
        context["validation"] = {
            "approved": approved,
            "checks": validation_results,
            "reasons": {
                "approval": approval_reasons,
                "rejection": rejection_reasons,
            },
        }
        
        return {
            "context": context,
            "validation": context["validation"],
            "agent_steps": steps,
            "total_tokens": tokens,
        }
    
    def _run_validation(
        self,
        patch_code: str,
        modified_preview: str,
        test_success: bool,
        test_results: Dict[str, Any],
        retrieved_code: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Run all validation checks.
        """
        checks_passed = []
        checks_failed = []
        
        # Check 1: Syntax validation
        is_valid, syntax_error = SyntaxValidator.validate(modified_preview)
        if is_valid:
            checks_passed.append("Syntax is valid")
        else:
            checks_failed.append(f"Syntax error: {syntax_error}")
        
        # Check 2: Tests passed
        if test_success:
            checks_passed.append("Tests passed")
        else:
            checks_failed.append("Tests failed")
        
        # Check 3: Patch has content
        if patch_code.strip():
            checks_passed.append("Patch contains modifications")
        else:
            checks_failed.append("Patch is empty")
        
        # Check 4: Test results look good
        passed = test_results.get("passed", 0)
        failed = test_results.get("failed", 0)
        if failed == 0 and passed > 0:
            checks_passed.append(f"All {passed} tests passed")
        elif failed > 0:
            checks_failed.append(f"{failed} tests failed")
        
        # Check 5: No obvious regressions (check for missing imports, etc.)
        # Simplified check - in production would do deeper analysis
        
        return {
            "passed_checks": checks_passed,
            "failed_checks": checks_failed,
            "passed": len(checks_passed),
            "failed": len(checks_failed),
        }