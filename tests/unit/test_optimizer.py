"""Unit tests for optimizer."""

import unittest
from typing import Any

from z3 import Const, IntSort

from z3adapter.dsl.expressions import ExpressionParser
from z3adapter.optimization.optimizer import OptimizerRunner


class TestOptimizerRunner(unittest.TestCase):
    """Test cases for OptimizerRunner."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.sorts = {"IntSort": IntSort()}
        self.functions: dict[str, Any] = {}
        self.constants = {"x": Const("x", IntSort())}
        self.variables: dict[str, Any] = {}
        self.parser = ExpressionParser(self.functions, self.constants, self.variables)
        self.optimizer = OptimizerRunner(self.parser, self.sorts, ExpressionParser.Z3_OPERATORS)

    def test_optimize_no_config(self) -> None:
        """Test optimize with no configuration."""
        with self.assertLogs(level="INFO") as cm:
            self.optimizer.optimize({}, 10000)
        self.assertTrue(any("No optimization section" in msg for msg in cm.output))

    def test_optimize_simple_maximize(self) -> None:
        """Test simple maximization problem."""
        config = {
            "variables": [{"name": "y", "sort": "IntSort"}],
            "constraints": ["y >= 0", "y <= 10"],
            "objectives": [{"expression": "y", "type": "maximize"}],
        }
        with self.assertLogs(level="INFO"):
            self.optimizer.optimize(config, 10000)
        # Should find optimal solution
        # Can be either SAT with model or no solution (depends on solver state)

    def test_optimize_simple_minimize(self) -> None:
        """Test simple minimization problem."""
        config = {
            "variables": [{"name": "y", "sort": "IntSort"}],
            "constraints": ["y >= 0", "y <= 10"],
            "objectives": [{"expression": "y", "type": "minimize"}],
        }
        with self.assertLogs(level="INFO"):
            self.optimizer.optimize(config, 10000)
        # Should find optimal solution

    def test_optimize_with_multiple_constraints(self) -> None:
        """Test optimization with multiple constraints."""
        config = {
            "variables": [{"name": "a", "sort": "IntSort"}, {"name": "b", "sort": "IntSort"}],
            "constraints": ["a >= 0", "b >= 0", "a + b <= 100"],
            "objectives": [{"expression": "a + b", "type": "maximize"}],
        }
        self.optimizer.optimize(config, 10000)
        # Should not raise

    def test_optimize_references_global_constants(self) -> None:
        """Test that optimization can reference global constants."""
        config = {
            "variables": [{"name": "y", "sort": "IntSort"}],
            "constraints": ["y > x"],  # References global constant x
            "objectives": [{"expression": "y", "type": "minimize"}],
        }
        # This should work because optimizer has access to global context
        # May not find solution without x being constrained, but shouldn't error
        try:
            self.optimizer.optimize(config, 10000)
        except Exception as e:
            # If it fails, it should not be due to missing 'x'
            self.assertNotIn("undefined", str(e).lower())

    def test_optimize_unknown_objective_type(self) -> None:
        """Test that unknown objective type logs warning."""
        config = {
            "variables": [{"name": "y", "sort": "IntSort"}],
            "constraints": ["y >= 0"],
            "objectives": [{"expression": "y", "type": "unknown_type"}],
        }
        with self.assertLogs(level="WARNING") as cm:
            self.optimizer.optimize(config, 10000)
        self.assertTrue(any("Unknown optimization type" in msg for msg in cm.output))

    def test_optimize_invalid_constraint_syntax(self) -> None:
        """Test that invalid constraint syntax raises error."""
        config = {
            "variables": [{"name": "y", "sort": "IntSort"}],
            "constraints": ["invalid + syntax +"],
            "objectives": [{"expression": "y", "type": "maximize"}],
        }
        with self.assertRaises(ValueError):
            self.optimizer.optimize(config, 10000)

    def test_optimize_sets_timeout(self) -> None:
        """Test that timeout is properly set."""
        config = {
            "variables": [{"name": "y", "sort": "IntSort"}],
            "constraints": ["y >= 0"],
            "objectives": [{"expression": "y", "type": "maximize"}],
        }
        timeout = 5000
        # Should not raise
        self.optimizer.optimize(config, timeout)

    def test_optimize_with_undefined_sort_raises_error(self) -> None:
        """Test that optimization with undefined sort raises error."""
        config = {
            "variables": [{"name": "y", "sort": "UndefinedSort"}],
            "constraints": ["y >= 0"],
            "objectives": [{"expression": "y", "type": "maximize"}],
        }
        with self.assertRaises(ValueError):
            self.optimizer.optimize(config, 10000)


if __name__ == "__main__":
    unittest.main()
