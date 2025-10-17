"""Abstract solver interface."""

from abc import ABC, abstractmethod
from typing import Any


class AbstractSolver(ABC):
    """Abstract base class for solver implementations."""

    @abstractmethod
    def add(self, constraint: Any) -> None:
        """Add a constraint to the solver."""
        raise NotImplementedError

    @abstractmethod
    def check(self, condition: Any = None) -> Any:
        """Check satisfiability of constraints."""
        raise NotImplementedError

    @abstractmethod
    def model(self) -> Any:
        """Get the model if SAT."""
        raise NotImplementedError

    @abstractmethod
    def set(self, param: str, value: Any) -> None:
        """Set solver parameter."""
        raise NotImplementedError
