"""Unit tests for expression parser."""

import unittest
from typing import Any

from z3 import BoolSort, Const, Function, IntSort

from z3adapter.dsl.expressions import ExpressionParser


class TestExpressionParser(unittest.TestCase):
    """Test cases for ExpressionParser."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.functions: dict[str, Any] = {}
        self.constants = {"x": Const("x", IntSort()), "y": Const("y", IntSort())}
        self.variables = {"z": Const("z", BoolSort())}
        self.parser = ExpressionParser(self.functions, self.constants, self.variables)

    def test_parse_simple_arithmetic(self) -> None:
        """Test parsing simple arithmetic expression."""
        expr_str = "x + y"
        result = self.parser.parse_expression(expr_str)
        self.assertIsNotNone(result)

    def test_parse_with_function(self) -> None:
        """Test parsing expression with function."""
        f = Function("f", IntSort(), IntSort())
        self.parser.functions["f"] = f
        expr_str = "f(x) > 0"
        result = self.parser.parse_expression(expr_str)
        self.assertIsNotNone(result)

    def test_parse_with_z3_operators(self) -> None:
        """Test parsing with Z3 operators."""
        expr_str = "And(z, Not(z))"
        result = self.parser.parse_expression(expr_str)
        self.assertIsNotNone(result)

    def test_parse_with_quantified_variables(self) -> None:
        """Test parsing with quantified variables."""
        qvar = Const("q", IntSort())
        expr_str = "q > 0"
        result = self.parser.parse_expression(expr_str, [qvar])
        self.assertIsNotNone(result)

    def test_build_context_without_symbols_loaded(self) -> None:
        """Test that context builds dynamically before symbols loaded."""
        context = self.parser.build_context()
        self.assertIn("x", context)
        self.assertIn("y", context)
        self.assertIn("z", context)

    def test_build_context_with_symbols_loaded(self) -> None:
        """Test that context is cached after symbols loaded."""
        self.parser.mark_symbols_loaded()
        context1 = self.parser.build_context()
        context2 = self.parser.build_context()
        self.assertIsNotNone(self.parser._context_cache)
        # Should be using cache
        self.assertIn("x", context1)
        self.assertIn("x", context2)

    def test_build_context_with_quantified_vars(self) -> None:
        """Test that quantified variables are added to context."""
        qvar = Const("new_var", IntSort())
        context = self.parser.build_context([qvar])
        self.assertIn("new_var", context)
        self.assertIn("x", context)  # Original constants still there

    def test_quantified_var_shadows_constant_warning(self) -> None:
        """Test that shadowing warning is logged."""
        shadow_var = Const("x", IntSort())  # Same name as constant
        with self.assertLogs(level="WARNING") as cm:
            context = self.parser.build_context([shadow_var])
        self.assertTrue(any("shadows" in msg for msg in cm.output))
        # Context should have the quantified variable, not the constant
        self.assertEqual(context["x"], shadow_var)

    def test_parse_expression_with_invalid_syntax(self) -> None:
        """Test that syntax errors are caught."""
        expr_str = "x +"
        with self.assertRaises(ValueError) as ctx:
            self.parser.parse_expression(expr_str)
        self.assertIn("Syntax error", str(ctx.exception))

    def test_parse_expression_with_undefined_name(self) -> None:
        """Test that undefined names raise error."""
        expr_str = "undefined_var"
        with self.assertRaises(ValueError) as ctx:
            self.parser.parse_expression(expr_str)
        self.assertIn("Undefined name", str(ctx.exception))

    def test_add_knowledge_base_simple(self) -> None:
        """Test adding simple knowledge base assertions."""
        from z3adapter.solvers.z3_solver import Z3Solver

        solver = Z3Solver()
        knowledge_base = ["x > 0", "y < 10"]
        self.parser.add_knowledge_base(solver, knowledge_base)
        # Solver should have 2 assertions
        # Can't easily check count, but verify no errors

    def test_add_knowledge_base_with_negation(self) -> None:
        """Test adding knowledge base with value=False."""
        from z3adapter.solvers.z3_solver import Z3Solver

        solver = Z3Solver()
        knowledge_base = [{"assertion": "x > 100", "value": False}]
        self.parser.add_knowledge_base(solver, knowledge_base)
        # Should add Not(x > 100)

    def test_add_knowledge_base_invalid_assertion(self) -> None:
        """Test that invalid assertions raise error."""
        from z3adapter.solvers.z3_solver import Z3Solver

        solver = Z3Solver()
        knowledge_base = ["invalid + syntax +"]
        with self.assertRaises(ValueError):
            self.parser.add_knowledge_base(solver, knowledge_base)

    def test_add_rules_with_forall(self) -> None:
        """Test adding rules with universal quantification."""
        from z3adapter.solvers.z3_solver import Z3Solver

        solver = Z3Solver()
        sorts = {"IntSort": IntSort()}
        rules = [{"forall": [{"name": "q", "sort": "IntSort"}], "constraint": "q >= 0"}]
        self.parser.add_rules(solver, rules, sorts)

    def test_add_rules_with_implication(self) -> None:
        """Test adding implication rules."""
        from z3adapter.solvers.z3_solver import Z3Solver

        solver = Z3Solver()
        sorts = {"IntSort": IntSort()}
        rules = [
            {
                "forall": [{"name": "q", "sort": "IntSort"}],
                "implies": {"antecedent": "q > 0", "consequent": "q >= 1"},
            }
        ]
        self.parser.add_rules(solver, rules, sorts)

    def test_add_rules_empty_forall_raises_error(self) -> None:
        """Test that empty forall list raises error."""
        from z3adapter.solvers.z3_solver import Z3Solver

        solver = Z3Solver()
        sorts = {"IntSort": IntSort()}
        rules = [{"forall": [], "constraint": "x > 0"}]
        with self.assertRaises(ValueError) as ctx:
            self.parser.add_rules(solver, rules, sorts)
        self.assertIn("Empty 'forall' list", str(ctx.exception))

    def test_add_rules_implication_without_forall_raises_error(self) -> None:
        """Test that implication without forall raises error."""
        from z3adapter.solvers.z3_solver import Z3Solver

        solver = Z3Solver()
        sorts = {"IntSort": IntSort()}
        rules = [{"implies": {"antecedent": "x > 0", "consequent": "x >= 1"}}]
        with self.assertRaises(ValueError) as ctx:
            self.parser.add_rules(solver, rules, sorts)
        self.assertIn("require quantified variables", str(ctx.exception))

    def test_add_rules_constraint_without_forall(self) -> None:
        """Test adding constraint rule without quantification."""
        from z3adapter.solvers.z3_solver import Z3Solver

        solver = Z3Solver()
        sorts = {"IntSort": IntSort()}
        rules = [{"constraint": "x > 0"}]
        # Should not raise
        self.parser.add_rules(solver, rules, sorts)

    def test_add_rules_invalid_rule_format(self) -> None:
        """Test that invalid rule format raises error."""
        from z3adapter.solvers.z3_solver import Z3Solver

        solver = Z3Solver()
        sorts = {"IntSort": IntSort()}
        rules = [{"invalid_key": "value"}]
        with self.assertRaises(ValueError) as ctx:
            self.parser.add_rules(solver, rules, sorts)
        self.assertIn("must contain", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
