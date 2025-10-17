"""JSON DSL backend using Python Z3 API."""

import io
import logging
from contextlib import redirect_stderr, redirect_stdout

from z3adapter.backends.abstract import Backend, VerificationResult
from z3adapter.interpreter import Z3JSONInterpreter
from z3adapter.reasoning.prompt_template import DSL_INSTRUCTIONS

logger = logging.getLogger(__name__)


class JSONBackend(Backend):
    """Backend for executing JSON DSL programs via Python Z3 API."""

    def __init__(self, verify_timeout: int = 10000, optimize_timeout: int = 100000) -> None:
        """Initialize JSON backend.

        Args:
            verify_timeout: Timeout for verification in milliseconds
            optimize_timeout: Timeout for optimization in milliseconds
        """
        self.verify_timeout = verify_timeout
        self.optimize_timeout = optimize_timeout

    def execute(self, program_path: str) -> VerificationResult:
        """Execute a JSON DSL program.

        Args:
            program_path: Path to JSON program file

        Returns:
            VerificationResult with answer and execution details
        """
        try:
            # Capture stdout and stderr for output logging
            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()

            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                interpreter = Z3JSONInterpreter(
                    program_path,
                    verify_timeout=self.verify_timeout,
                    optimize_timeout=self.optimize_timeout,
                )
                interpreter.run()

            # Get structured verification counts from interpreter
            sat_count, unsat_count = interpreter.get_verification_counts()

            # Combine output for logging
            full_output = stdout_capture.getvalue() + stderr_capture.getvalue()

            # Determine answer based on verification results
            answer = self.determine_answer(sat_count, unsat_count)

            return VerificationResult(
                answer=answer,
                sat_count=sat_count,
                unsat_count=unsat_count,
                output=full_output,
                success=True,
            )

        except Exception as e:
            logger.error(f"Error executing JSON program: {e}")
            return VerificationResult(
                answer=None,
                sat_count=0,
                unsat_count=0,
                output="",
                success=False,
                error=str(e),
            )

    def get_file_extension(self) -> str:
        """Get the file extension for JSON programs.

        Returns:
            ".json"
        """
        return ".json"

    def get_prompt_template(self) -> str:
        """Get the prompt template for JSON DSL generation.

        Returns:
            JSON DSL prompt template
        """
        return DSL_INSTRUCTIONS
