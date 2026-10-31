"""Agentic backend: in-process Z3 execution for SMT2 programs.

The agentic paradigm doesn't generate one program file up front - the model
iterates against an SMT-LIB scratchpad (see ``z3adapter.agentic``). This
Backend implementation exists so the rest of the library (EvaluationPipeline,
program saving, prompt-template plumbing) keeps working uniformly: it
executes ``.smt2`` files in-process via the Z3 Python API, so the final
program of an agentic trajectory can be saved and independently re-checked
without a Z3 CLI binary on PATH.

Semantics warning - read before re-verifying trajectories
---------------------------------------------------------
``execute()`` reports the *program-level* satisfiability, with the same
convention as every other Backend: ``sat -> answer=True``,
``unsat -> answer=False``. That is NOT the question's answer for an agentic
trajectory: under the proof-by-contradiction discipline the saved program
asserts the *negation* of the verified answer, so ``unsat``
(``answer=False`` at the program level) is precisely what CONFIRMS the
proof. To re-check a trajectory, use :meth:`reverify` with the
``proof_status`` recorded on the result - it encapsulates the convention so
callers never have to invert booleans by hand.
"""

import logging

from z3adapter.agentic.agent import DEFAULT_SYSTEM_PROMPT, ProofStatus
from z3adapter.agentic.executor import Z3Executor, verdict_counts, z3_result_is_useful
from z3adapter.backends.abstract import Backend, VerificationResult

logger = logging.getLogger(__name__)

# Which Z3 verdict re-establishes a proof of each status. UNVERIFIED has no
# entry: there is nothing to re-establish.
_EXPECTED_VERDICT = {
    ProofStatus.PROOF_BY_CONTRADICTION: "unsat",
    ProofStatus.SAT_WITNESS: "sat",
}


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

        Note: ``answer`` is the program-level satisfiability (sat→True,
        unsat→False), consistent with the other backends - NOT the question's
        answer for a proof-by-contradiction trajectory. See the module
        docstring and :meth:`reverify`.

        Args:
            program_path: Path to SMT2 program file

        Returns:
            VerificationResult with program-level verdict and execution details
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
        sat_count, unsat_count = verdict_counts(z3_out.get("sat_result"))

        return VerificationResult(
            answer=self.determine_answer(sat_count, unsat_count),
            sat_count=sat_count,
            unsat_count=unsat_count,
            output=z3_out.get("output") or "",
            success=bool(z3_out.get("success")),
            error=z3_out.get("error"),
        )

    def reverify(self, program_path: str, proof_status: ProofStatus | str | None) -> bool:
        """Re-run a saved trajectory program and check that the proof still holds.

        Args:
            program_path: Path to the ``.smt2`` program saved from a query
                (``pot.query(..., save_program=True, program_path=...)``).
            proof_status: The ``proof_status`` recorded on the QueryResult /
                AgenticResult that produced the program (enum or its string
                value).

        Returns:
            True when the program still yields the verdict that backed the
            original answer (``unsat`` for PROOF_BY_CONTRADICTION, ``sat``
            for SAT_WITNESS) with a clean, usable result. False for
            UNVERIFIED/None statuses - an unverified answer has no proof to
            re-establish - or when the verdict changed or errored.

        Raises:
            OSError: If the program file cannot be read - a missing proof
                artifact is a caller error, not a failed re-verification.
        """
        if proof_status is None:
            return False
        try:
            status = ProofStatus(proof_status)
        except ValueError:
            return False
        expected = _EXPECTED_VERDICT.get(status)
        if expected is None:
            return False

        with open(program_path) as f:
            smt_code = f.read()
        z3_out = self.executor.execute(smt_code)
        return z3_result_is_useful(z3_out) and z3_out.get("sat_result") == expected

    def get_file_extension(self) -> str:
        """Agentic trajectories produce standard SMT2 programs."""
        return ".smt2"

    def get_prompt_template(self) -> str:
        """The agentic system prompt (tool-loop protocol).

        Note: this prompt describes a *tool loop*; it is not suitable for
        single-shot generation via Z3ProgramGenerator.
        """
        return DEFAULT_SYSTEM_PROMPT
