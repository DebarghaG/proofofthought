"""Agentic backend: in-process Z3 execution for SMT2 programs.

The agentic paradigm doesn't generate one program file up front - the model
iterates against an SMT-LIB scratchpad (see ``z3adapter.agentic``). This
Backend implementation exists so the rest of the library (EvaluationPipeline,
program saving, prompt-template plumbing) keeps working uniformly: it
executes ``.smt2`` files in-process via the Z3 Python API, so the final
program of an agentic trajectory can be saved and independently re-verified
without a Z3 CLI binary on PATH.
"""

import logging

from z3adapter.agentic.agent import DEFAULT_SYSTEM_PROMPT
from z3adapter.agentic.executor import Z3Executor
from z3adapter.backends.abstract import Backend, VerificationResult

logger = logging.getLogger(__name__)


class AgenticBackend(Backend):
    """Backend for re-executing agentic SMT2 programs via the Z3 Python API."""

    def __init__(self, verify_timeout: int = 30000) -> None:
        """Initialize agentic backend.

        Args:
            verify_timeout: Timeout for verification in milliseconds
        """
        self.verify_timeout = verify_timeout
        self.executor = Z3Executor(timeout_ms=verify_timeout)

    def execute(self, program_path: str) -> VerificationResult:
        """Execute an SMT2 program file in-process.

        Args:
            program_path: Path to SMT2 program file

        Returns:
            VerificationResult with answer and execution details
        """
        try:
            with open(program_path) as f:
                smt_code = f.read()
        except OSError as e:
            error_msg = f"Failed to read program file: {e}"
            logger.error(error_msg)
            return VerificationResult(
                answer=None,
                sat_count=0,
                unsat_count=0,
                output="",
                success=False,
                error=error_msg,
            )

        z3_out = self.executor.execute(smt_code)
        sat_result = z3_out.get("sat_result")
        sat_count = 1 if sat_result == "sat" else 0
        unsat_count = 1 if sat_result == "unsat" else 0

        return VerificationResult(
            answer=self.determine_answer(sat_count, unsat_count),
            sat_count=sat_count,
            unsat_count=unsat_count,
            output=z3_out.get("output") or "",
            success=bool(z3_out.get("success")),
            error=z3_out.get("error"),
        )

    def get_file_extension(self) -> str:
        """Agentic trajectories produce standard SMT2 programs."""
        return ".smt2"

    def get_prompt_template(self) -> str:
        """The agentic system prompt (tool-loop protocol)."""
        return DEFAULT_SYSTEM_PROMPT
