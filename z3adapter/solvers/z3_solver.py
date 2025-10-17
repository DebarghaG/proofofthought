"""Z3 solver implementation."""

from typing import Any

from z3 import Solver

from z3adapter.solvers.abstract import AbstractSolver


class Z3Solver(AbstractSolver):
    """Z3 solver implementation."""

    def __init__(self) -> None:
        self.solver = Solver()

    def add(self, constraint: Any) -> None:
        """Add a constraint to the Z3 solver."""
        self.solver.add(constraint)

    def check(self, condition: Any = None) -> Any:
        """Check satisfiability with optional condition."""
        if condition is not None:
            return self.solver.check(condition)
        return self.solver.check()

    def model(self) -> Any:
        """Return the satisfying model."""
        return self.solver.model()

    def set(self, param: str, value: Any) -> None:
        """Set Z3 solver parameter."""
        self.solver.set(param, value)
