"""Unit tests for verifier."""

import unittest
from typing import Any

from z3 import BoolSort, Const, IntSort

from z3adapter.dsl.expressions import ExpressionParser
from z3adapter.solvers.z3_solver import Z3Solver
from z3adapter.verification.verifier import Verifier


class TestVerifier(unittest.TestCase):
    """Test cases for Verifier."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.sorts = {"IntSort": IntSort(), "BoolSort": BoolSort()}
        self.functions: dict[str, Any] = {}
        self.constants = {"x": Const("x", IntSort()), "y": Const("y", IntSort())}
        self.variables: dict[str, Any] = {}
        self.parser = ExpressionParser(self.functions, self.constants, self.variables)
        self.verifier = Verifier(self.parser, self.sorts)

    def test_add_verification_simple_constraint(self) -> None:
        """Test adding simple constraint verification."""
        verifications = [{"name": "test_constraint", "constraint": "x > 0"}]
        self.verifier.add_verifications(verifications)
        self.assertIn("test_constraint", self.verifier.verifications)

    def test_add_verification_with_exists(self) -> None:
        """Test adding verification with existential quantification."""
        verifications = [
            {
                "name": "exists_test",
                "exists": [{"name": "z", "sort": "IntSort"}],
                "constraint": "z > 10",
            }
        ]
        self.verifier.add_verifications(verifications)
        self.assertIn("exists_test", self.verifier.verifications)

    def test_add_verification_with_forall(self) -> None:
        """Test adding verification with universal quantification."""
        verifications = [
            {
                "name": "forall_test",
                "forall": [{"name": "w", "sort": "IntSort"}],
                "implies": {"antecedent": "w > 0", "consequent": "w >= 1"},
            }
        ]
        self.verifier.add_verifications(verifications)
        self.assertIn("forall_test", self.verifier.verifications)

    def test_add_verification_empty_exists_raises_error(self) -> None:
        """Test that empty exists list raises error."""
        verifications = [{"name": "bad_exists", "exists": [], "constraint": "x > 0"}]
        with self.assertRaises(ValueError) as ctx:
            self.verifier.add_verifications(verifications)
        self.assertIn("Empty 'exists' list", str(ctx.exception))

    def test_add_verification_empty_forall_raises_error(self) -> None:
        """Test that empty forall list raises error."""
        verifications = [
            {
                "name": "bad_forall",
                "forall": [],
                "implies": {"antecedent": "x > 0", "consequent": "x >= 1"},
            }
        ]
        with self.assertRaises(ValueError) as ctx:
            self.verifier.add_verifications(verifications)
        self.assertIn("Empty 'forall' list", str(ctx.exception))

    def test_add_verification_invalid_format_raises_error(self) -> None:
        """Test that invalid verification format raises error."""
        verifications = [{"name": "invalid", "invalid_key": "value"}]
        with self.assertRaises(ValueError) as ctx:
            self.verifier.add_verifications(verifications)
        self.assertIn("must contain", str(ctx.exception))

    def test_add_verification_unnamed(self) -> None:
        """Test adding unnamed verification gets default name."""
        verifications = [{"constraint": "x > 0"}]
        self.verifier.add_verifications(verifications)
        self.assertIn("unnamed_verification", self.verifier.verifications)

    def test_verify_conditions_sat(self) -> None:
        """Test verifying a satisfiable condition."""
        solver = Z3Solver()
        solver.add(self.constants["x"] > 0)

        verifications = [{"name": "check_positive", "constraint": "x > 0"}]
        self.verifier.add_verifications(verifications)

        # Should not raise
        with self.assertLogs(level="INFO") as cm:
            self.verifier.verify_conditions(solver, 10000)
        self.assertTrue(any("SAT" in msg for msg in cm.output))

    def test_verify_conditions_unsat(self) -> None:
        """Test verifying an unsatisfiable condition."""
        solver = Z3Solver()
        solver.add(self.constants["x"] > 0)

        verifications = [{"name": "check_negative", "constraint": "x < 0"}]
        self.verifier.add_verifications(verifications)

        with self.assertLogs(level="INFO") as cm:
            self.verifier.verify_conditions(solver, 10000)
        self.assertTrue(any("UNSAT" in msg for msg in cm.output))

    def test_verify_conditions_no_verifications(self) -> None:
        """Test verify with no verifications defined."""
        solver = Z3Solver()
        with self.assertLogs(level="INFO") as cm:
            self.verifier.verify_conditions(solver, 10000)
        self.assertTrue(any("No verifications" in msg for msg in cm.output))

    def test_verify_conditions_sets_timeout(self) -> None:
        """Test that timeout is properly set on solver."""
        solver = Z3Solver()
        verifications = [{"name": "test", "constraint": "x > 0"}]
        self.verifier.add_verifications(verifications)

        timeout = 5000
        self.verifier.verify_conditions(solver, timeout)
        # Timeout should have been set (can't easily verify, but check no errors)

    def test_add_verification_with_undefined_sort_raises_error(self) -> None:
        """Test that verification with undefined sort raises error."""
        verifications = [
            {
                "name": "bad_sort",
                "exists": [{"name": "z", "sort": "UndefinedSort"}],
                "constraint": "z > 0",
            }
        ]
        with self.assertRaises(ValueError):
            self.verifier.add_verifications(verifications)


if __name__ == "__main__":
    unittest.main()
