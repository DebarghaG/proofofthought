"""Staged SMT2 backend with conversion tracking."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from z3adapter._z3 import resolve_z3_path
from z3adapter.backends.abstract import Backend, VerificationResult
from z3adapter.backends.smt2.ir import ConversionContext
from z3adapter.backends.smt2.parser import ExecutionResult, Z3OutputParser
from z3adapter.backends.smt2.stages import Pipeline

logger = logging.getLogger(__name__)
VERIFICATION_MODE_MARKER = re.compile(r"^\s*;\s*Verification mode:\s*(\w+)\s*$", re.MULTILINE)


class StagedSMT2Backend(Backend):
    """
    Staged SMT2 backend with conversion tracking IR.

    Features:
    - Staged pipeline (types -> functions -> enums -> KB -> VCs -> solve)
    - Conversion tracking for incremental generation
    - Multiple queries with structured results
    - LLM-friendly context preservation
    """

    def __init__(
        self,
        verify_timeout: int = 10000,
        z3_path: str = "z3",
    ) -> None:
        """
        Initialize StagedSMT2Backend.

        Args:
            verify_timeout: Timeout for verification in milliseconds
            z3_path: Path to Z3 executable
        """
        self.verify_timeout = verify_timeout
        self.z3_path = resolve_z3_path(z3_path)
        self.parser = Z3OutputParser()

        # Current pipeline and context (for incremental use)
        self._pipeline: Pipeline | None = None
        self._last_context: ConversionContext | None = None

    def execute(self, program_path: str) -> VerificationResult:
        """
        Execute an SMT2 program via Z3 CLI.

        This method handles raw SMT-LIB files (for backward compatibility).
        Use execute_config() for structured execution with IR tracking.
        """
        try:
            timeout_seconds = self.verify_timeout // 1000
            program_text = Path(program_path).read_text(encoding="utf-8")

            result = subprocess.run(
                [self.z3_path, f"-T:{timeout_seconds}", program_path],
                capture_output=True,
                text=True,
                timeout=timeout_seconds + 10,
            )

            output = result.stdout + result.stderr

            exec_result = self.parser.parse(output)

            if exec_result.non_model_errors:
                return VerificationResult(
                    answer=None,
                    sat_count=exec_result.sat_count,
                    unsat_count=exec_result.unsat_count,
                    output=output,
                    success=False,
                    error=exec_result.error,
                    failure_code="solver_error",
                )

            if exec_result.sat_count == 0 and exec_result.unsat_count == 0:
                return VerificationResult(
                    answer=None,
                    sat_count=0,
                    unsat_count=0,
                    output=output,
                    success=False,
                    error=exec_result.error or output.strip() or f"Z3 exited with code {result.returncode}",
                    failure_code="no_solver_result",
                )

            query_modes = self._extract_query_modes(program_text)
            answer = self._determine_answer(exec_result, query_modes)

            return VerificationResult(
                answer=answer,
                sat_count=exec_result.sat_count,
                unsat_count=exec_result.unsat_count,
                output=output,
                success=True,
            )

        except subprocess.TimeoutExpired:
            error_msg = (
                f"Z3 execution timed out after {self.verify_timeout // 1000}s. "
                f"The SMT2 program may be too complex or contain an infinite loop."
            )
            logger.error(error_msg)
            return VerificationResult(
                answer=None,
                sat_count=0,
                unsat_count=0,
                output="",
                success=False,
                error=error_msg,
                failure_code="solver_timeout",
            )
        except FileNotFoundError:
            error_msg = f"Z3 executable not found: '{self.z3_path}'"
            logger.error(error_msg)
            return VerificationResult(
                answer=None,
                sat_count=0,
                unsat_count=0,
                output="",
                success=False,
                error=error_msg,
                failure_code="z3_not_found",
            )
        except Exception as e:
            error_msg = f"Error executing SMT2 program: {e}"
            logger.error(error_msg)
            return VerificationResult(
                answer=None,
                sat_count=0,
                unsat_count=0,
                output="",
                success=False,
                error=str(e),
                failure_code="execution_error",
            )

    def _extract_query_modes(self, program_text: str) -> list[str]:
        """Extract verification modes from query block comments."""
        return [match.group(1).strip().lower() for match in VERIFICATION_MODE_MARKER.finditer(program_text)]

    def _determine_answer(self, exec_result: ExecutionResult, query_modes: list[str]) -> bool | None:
        """Determine the boolean answer using the configured verification mode(s)."""
        answers: list[bool | None] = []
        normalized_modes = list(query_modes)
        if len(normalized_modes) < len(exec_result.queries):
            normalized_modes.extend(["consistency"] * (len(exec_result.queries) - len(normalized_modes)))

        for index, query in enumerate(exec_result.queries):
            mode = normalized_modes[index] if index < len(normalized_modes) else "consistency"
            if query.status not in {"sat", "unsat"}:
                answers.append(None)
                continue

            if mode == "entailment":
                answers.append(query.status == "unsat")
            else:
                answers.append(query.status == "sat")

        concrete_answers = [answer for answer in answers if answer is not None]
        if len(concrete_answers) != len(answers):
            return None
        if all(answer is True for answer in concrete_answers):
            return True
        if all(answer is False for answer in concrete_answers):
            return False
        return None

    def execute_config(
        self,
        config: dict[str, Any],
        save_program: bool = False,
        program_path: str | None = None,
    ) -> tuple[VerificationResult, ExecutionResult]:
        """
        Execute a DSL configuration through the staged pipeline.

        Args:
            config: DSL configuration dictionary
            save_program: Whether to save the generated SMT-LIB
            program_path: Path to save (or auto-generate temp file)

        Returns:
            Tuple of (VerificationResult, ExecutionResult)
        """
        # Create pipeline and generate SMT-LIB
        pipeline = Pipeline()
        smt2_program = pipeline.run(config)

        # Store for context access
        self._pipeline = pipeline
        self._last_context = pipeline.get_context()

        # Get query names for result parsing
        query_names = [q.name for q in self._last_context.queries.values()]

        # Write to file
        if program_path:
            path = Path(program_path)
        else:
            fd, temp_path = tempfile.mkstemp(suffix=".smt2")
            path = Path(temp_path)

        path.write_text(smt2_program)

        logger.info(f"Generated SMT-LIB program: {path}")
        logger.debug(f"Program:\n{smt2_program}")

        # Execute
        verify_result = self.execute(str(path))

        # Parse with query names
        exec_result = self.parser.parse(verify_result.output, query_names)

        # Clean up temp file if not saving
        if not save_program and not program_path:
            path.unlink(missing_ok=True)

        return verify_result, exec_result

    def generate_smt2(self, config: dict[str, Any]) -> str:
        """
        Generate SMT-LIB code from configuration without executing.

        Args:
            config: DSL configuration dictionary

        Returns:
            SMT-LIB program string
        """
        pipeline = Pipeline()
        smt2_program = pipeline.run(config)

        self._pipeline = pipeline
        self._last_context = pipeline.get_context()

        return smt2_program

    def build_foundation(
        self,
        config: dict[str, Any],
        through_stage: str = "rules",
    ) -> str:
        """
        Build foundation SMT-LIB (sorts, functions, constants, KB, rules).

        This can be reused for multiple verification queries.

        Args:
            config: DSL configuration
            through_stage: Stage to run through (default: "rules")

        Returns:
            SMT-LIB code for the foundation
        """
        pipeline = Pipeline()
        foundation = pipeline.run_through(through_stage, config)

        self._pipeline = pipeline
        self._last_context = pipeline.get_context()

        return foundation

    def add_query(
        self,
        verification: dict[str, Any],
        foundation: str | None = None,
    ) -> str:
        """
        Add a verification query on top of existing foundation.

        Args:
            verification: Verification definition
            foundation: Optional foundation SMT-LIB (uses cached if None)

        Returns:
            Complete SMT-LIB program with query
        """
        if foundation is None and self._pipeline is None:
            raise ValueError("No foundation built. Call build_foundation() first.")

        # Use existing pipeline context
        from z3adapter.backends.smt2.emitter import ExpressionEmitter

        ctx = self._last_context or ConversionContext()
        emitter = ExpressionEmitter(ctx)

        # Save variable state to avoid polluting context across queries
        saved_variables = dict(ctx.variables)

        lines = []
        if foundation:
            lines.append(foundation)

        # Generate query
        name = verification.get("name", "query")

        if "exists" in verification:
            exists_vars = verification["exists"]
            var_bindings = []
            for v in exists_vars:
                sort_name = v["sort"]
                smt_sort = ctx.resolve_sort_name(sort_name)
                var_bindings.append(f"({v['name']} {smt_sort})")
                ctx.variables[v["name"]] = sort_name

            constraint = emitter.emit(verification["constraint"])
            bindings_str = " ".join(var_bindings)
            smt_expr = f"(exists ({bindings_str}) {constraint})"

        elif "forall" in verification:
            forall_vars = verification["forall"]
            var_bindings = []
            for v in forall_vars:
                sort_name = v["sort"]
                smt_sort = ctx.resolve_sort_name(sort_name)
                var_bindings.append(f"({v['name']} {smt_sort})")
                ctx.variables[v["name"]] = sort_name

            antecedent = emitter.emit(verification["implies"]["antecedent"])
            consequent = emitter.emit(verification["implies"]["consequent"])
            bindings_str = " ".join(var_bindings)
            smt_expr = f"(forall ({bindings_str}) (=> {antecedent} {consequent}))"

        elif "constraint" in verification:
            smt_expr = emitter.emit(verification["constraint"])
        else:
            ctx.variables = saved_variables
            raise ValueError("Verification must have 'constraint', 'exists', or 'forall'")

        # Restore variable state after emitting query
        ctx.variables = saved_variables

        lines.append(f"; Query: {name}")
        lines.append("; Verification mode: consistency")
        lines.append("(push 1)")
        lines.append(f"(assert {smt_expr})")
        lines.append("(check-sat)")
        lines.append("(pop 1)")

        return "\n".join(lines)

    def get_context(self) -> ConversionContext | None:
        """Get the current conversion context."""
        return self._last_context

    def get_context_summary(self) -> str:
        """Get a summary of the current context for LLM prompts."""
        if self._last_context:
            return self._last_context.to_summary()
        return "; No context available"

    def execute_from_string(self, smt2_program: str) -> VerificationResult:
        """
        Execute an SMT-LIB program from a string.

        Args:
            smt2_program: SMT-LIB program text

        Returns:
            VerificationResult with answer and execution details
        """
        # Write to temp file
        fd, temp_path = tempfile.mkstemp(suffix=".smt2")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(smt2_program)

            # Execute
            result = self.execute(temp_path)
            return result
        finally:
            # Clean up
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def get_file_extension(self) -> str:
        return ".smt2"

    def get_prompt_template(self) -> str:
        from z3adapter.reasoning.smt2_prompt_template import SMT2_INSTRUCTIONS

        return SMT2_INSTRUCTIONS
