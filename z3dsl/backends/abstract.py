"""Abstract backend interface for Z3 DSL execution."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class VerificationResult:
    """Result of Z3 verification execution."""

    answer: bool | None  # True (SAT), False (UNSAT), or None (ambiguous/error)
    sat_count: int
    unsat_count: int
    output: str
    success: bool
    error: str | None = None


class Backend(ABC):
    """Abstract base class for Z3 DSL execution backends."""

    @abstractmethod
    def execute(self, program_path: str) -> VerificationResult:
        """Execute a program and return verification results.

        Args:
            program_path: Path to the program file

        Returns:
            VerificationResult with answer and execution details
        """
        pass

    @abstractmethod
    def get_file_extension(self) -> str:
        """Get the file extension for this backend's programs.

        Returns:
            File extension including dot (e.g., ".json", ".smt2")
        """
        pass

    @abstractmethod
    def get_prompt_template(self) -> str:
        """Get the prompt template for LLM program generation.

        Returns:
            Prompt template string
        """
        pass

    def determine_answer(self, sat_count: int, unsat_count: int) -> bool | None:
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
            return None
