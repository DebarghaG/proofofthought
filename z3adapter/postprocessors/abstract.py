"""Abstract base class for postprocessors."""

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from z3adapter.backends.abstract import Backend
    from z3adapter.reasoning.program_generator import Z3ProgramGenerator
    from z3adapter.reasoning.proof_of_thought import QueryResult

logger = logging.getLogger(__name__)


class Postprocessor(ABC):
    """Abstract base class for all postprocessing techniques.

    Postprocessors enhance reasoning quality by applying various strategies
    after the initial answer is obtained. They work with both JSON and SMT2 backends.

    Example:
        >>> from z3adapter.postprocessors import SelfRefine
        >>> postprocessor = SelfRefine(num_iterations=2)
        >>> improved_result = postprocessor.process(
        ...     question="...",
        ...     initial_result=result,
        ...     generator=generator,
        ...     backend=backend,
        ...     llm_client=client,
        ... )
    """

    def __init__(self, name: str | None = None):
        """Initialize postprocessor.

        Args:
            name: Optional name for this postprocessor instance
        """
        self.name = name or self.__class__.__name__

    @abstractmethod
    def process(
        self,
        question: str,
        initial_result: "QueryResult",
        generator: "Z3ProgramGenerator",
        backend: "Backend",
        llm_client: Any,
        **kwargs: Any,
    ) -> "QueryResult":
        """Process and potentially improve the initial result.

        Args:
            question: Original question being answered
            initial_result: Initial QueryResult from ProofOfThought
            generator: Program generator for creating new programs
            backend: Execution backend (JSON or SMT2)
            llm_client: LLM client for additional queries
            **kwargs: Additional arguments specific to the postprocessor

        Returns:
            Enhanced QueryResult (may be same as initial if no improvement)
        """
        pass

    def __repr__(self) -> str:
        """String representation."""
        return f"{self.__class__.__name__}(name='{self.name}')"
