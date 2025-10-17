"""SMT2 backend using Z3 command-line interface."""

import logging
import re
import shutil
import subprocess

from z3adapter.backends.abstract import Backend, VerificationResult
from z3adapter.reasoning.smt2_prompt_template import SMT2_INSTRUCTIONS

logger = logging.getLogger(__name__)


class SMT2Backend(Backend):
    """Backend for executing SMT2 programs via Z3 CLI."""

    def __init__(self, verify_timeout: int = 10000, z3_path: str = "z3") -> None:
        """Initialize SMT2 backend.

        Args:
            verify_timeout: Timeout for verification in milliseconds
            z3_path: Path to Z3 executable (default: "z3" from PATH)

        Raises:
            FileNotFoundError: If Z3 executable is not found
        """
        self.verify_timeout = verify_timeout
        self.z3_path = z3_path

        # Validate Z3 is available
        if not shutil.which(z3_path):
            raise FileNotFoundError(
                f"Z3 executable not found: '{z3_path}'\n"
                f"Please install Z3:\n"
                f"  - pip install z3-solver\n"
                f"  - Or download from: https://github.com/Z3Prover/z3/releases\n"
                f"  - Or specify custom path: SMT2Backend(z3_path='/path/to/z3')"
            )

    def execute(self, program_path: str) -> VerificationResult:
        """Execute an SMT2 program via Z3 CLI.

        Args:
            program_path: Path to SMT2 program file

        Returns:
            VerificationResult with answer and execution details
        """
        try:
            # Convert timeout from milliseconds to seconds for Z3
            timeout_seconds = self.verify_timeout // 1000

            # Run Z3 on the SMT2 file
            # -T:timeout sets soft timeout in seconds
            # -smt2 ensures SMT2 mode (usually auto-detected from extension)
            result = subprocess.run(
                [self.z3_path, f"-T:{timeout_seconds}", program_path],
                capture_output=True,
                text=True,
                timeout=timeout_seconds + 10,  # Hard timeout slightly longer
            )

            output = result.stdout + result.stderr

            # Parse Z3 output for sat/unsat
            sat_count, unsat_count = self._parse_z3_output(output)

            # Determine answer
            answer = self.determine_answer(sat_count, unsat_count)

            return VerificationResult(
                answer=answer,
                sat_count=sat_count,
                unsat_count=unsat_count,
                output=output,
                success=True,
            )

        except subprocess.TimeoutExpired:
            error_msg = (
                f"Z3 execution timed out after {timeout_seconds}s. "
                f"The SMT2 program may be too complex or contain an infinite loop. "
                f"Try increasing the timeout or simplifying the problem."
            )
            logger.error(error_msg)
            return VerificationResult(
                answer=None,
                sat_count=0,
                unsat_count=0,
                output="",
                success=False,
                error=error_msg,
            )
        except FileNotFoundError:
            error_msg = (
                f"Z3 executable not found: '{self.z3_path}'\n"
                f"This error should have been caught during initialization. "
                f"Z3 may have been removed or PATH changed."
            )
            logger.error(error_msg)
            return VerificationResult(
                answer=None,
                sat_count=0,
                unsat_count=0,
                output="",
                success=False,
                error=error_msg,
            )
        except Exception as e:
            error_msg = f"Error executing SMT2 program: {e}\nProgram path: {program_path}"
            logger.error(error_msg)
            return VerificationResult(
                answer=None,
                sat_count=0,
                unsat_count=0,
                output="",
                success=False,
                error=error_msg,
            )

    def _parse_z3_output(self, output: str) -> tuple[int, int]:
        """Parse Z3 output to count sat/unsat results.

        Args:
            output: Raw Z3 output text

        Returns:
            Tuple of (sat_count, unsat_count)
        """
        # Count occurrences of sat/unsat in output
        # Use negative lookbehind to exclude "unsat" from "sat" matches
        # Pattern: match "sat" only when NOT preceded by "un"
        sat_pattern = r"(?<!un)\bsat\b"
        unsat_pattern = r"\bunsat\b"

        sat_matches = re.findall(sat_pattern, output, re.IGNORECASE)
        unsat_matches = re.findall(unsat_pattern, output, re.IGNORECASE)

        sat_count = len(sat_matches)
        unsat_count = len(unsat_matches)

        logger.debug(f"Parsed Z3 output: sat={sat_count}, unsat={unsat_count}")
        return sat_count, unsat_count

    def get_file_extension(self) -> str:
        """Get the file extension for SMT2 programs.

        Returns:
            ".smt2"
        """
        return ".smt2"

    def get_prompt_template(self) -> str:
        """Get the prompt template for SMT2 generation.

        Returns:
            SMT2 prompt template
        """
        return SMT2_INSTRUCTIONS
