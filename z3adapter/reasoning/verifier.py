"""Z3 Verifier module for robust execution and output parsing."""

import io
import logging
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass

from z3adapter.interpreter import Z3JSONInterpreter

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result of Z3 verification execution."""

    answer: bool | None  # True (SAT), False (UNSAT), or None (ambiguous/error)
    sat_count: int
    unsat_count: int
    output: str
    success: bool
    error: str | None = None


class Z3Verifier:
    """Robust Z3 interpreter execution and result parsing."""

    def __init__(self, verify_timeout: int = 10000, optimize_timeout: int = 100000) -> None:
        """Initialize the Z3 Verifier.

        Args:
            verify_timeout: Timeout for verification in milliseconds
            optimize_timeout: Timeout for optimization in milliseconds
        """
        self.verify_timeout = verify_timeout
        self.optimize_timeout = optimize_timeout

    def verify(self, json_path: str) -> VerificationResult:
        """Execute Z3 interpreter on a JSON program and parse results.

        Args:
            json_path: Path to JSON DSL program file

        Returns:
            VerificationResult with answer and execution details
        """
        try:
            # Capture stdout and stderr for output logging
            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()

            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                interpreter = Z3JSONInterpreter(
                    json_path,
                    verify_timeout=self.verify_timeout,
                    optimize_timeout=self.optimize_timeout,
                )
                interpreter.run()

            # Get structured verification counts from interpreter
            sat_count, unsat_count = interpreter.get_verification_counts()

            # Combine output for logging
            full_output = stdout_capture.getvalue() + stderr_capture.getvalue()

            # Determine answer based on verification results
            answer = self._determine_answer(sat_count, unsat_count)

            return VerificationResult(
                answer=answer,
                sat_count=sat_count,
                unsat_count=unsat_count,
                output=full_output,
                success=True,
            )

        except Exception as e:
            logger.error(f"Error executing Z3 interpreter: {e}")
            return VerificationResult(
                answer=None,
                sat_count=0,
                unsat_count=0,
                output="",
                success=False,
                error=str(e),
            )

    def _determine_answer(self, sat_count: int, unsat_count: int) -> bool | None:
        """Determine boolean answer from SAT/UNSAT counts.

        Args:
            sat_count: Number of SAT occurrences
            unsat_count: Number of UNSAT occurrences

        Returns:
            True if SAT only, False if UNSAT only, None if ambiguous
        """
        if sat_count > 0 and unsat_count == 0:
            return True
        elif unsat_count > 0 and sat_count == 0:
            return False
        else:
            # Ambiguous: both or neither
            logger.warning(f"Ambiguous verification result: SAT={sat_count}, UNSAT={unsat_count}")
            return None
