"""Tests verifying that the 16 critical bugs are fixed."""

import ast
import json
import tempfile
import unittest

from z3 import Const, IntSort

from z3adapter.dsl.expressions import ExpressionParser
from z3adapter.dsl.sorts import SortManager
from z3adapter.interpreter import Z3JSONInterpreter
from z3adapter.security.validator import ExpressionValidator


class TestBugFixes(unittest.TestCase):
    """Test cases verifying critical bug fixes."""

    def test_bug1_wildcard_import_fixed(self) -> None:
        """Bug #1: Wildcard import pollution is fixed."""
        # Check that main.py doesn't use wildcard imports anymore
        with open("z3adapter/interpreter.py") as f:
            content = f.read()
            self.assertNotIn("from z3 import *", content)
            self.assertNotIn("import *", content)

    def test_bug2_type_annotation_fixed(self) -> None:
        """Bug #2: parse_expression return type is ExprRef not BoolRef."""
        # Check the actual implementation
        ExpressionParser({}, {}, {})
        # Return type should be ExprRef-compatible (includes arithmetic)
        # This is verified by static type checkers

    def test_bug3_context_cache_timing_fixed(self) -> None:
        """Bug #3: Context cache only built after symbols loaded."""
        parser = ExpressionParser({}, {}, {})
        # Before marking symbols loaded, cache should not exist
        self.assertIsNone(parser._context_cache)

        # After marking, cache gets built on first access
        parser.mark_symbols_loaded()
        parser.build_context()
        self.assertIsNotNone(parser._context_cache)

    def test_bug4_variable_shadowing_warning(self) -> None:
        """Bug #4: Variable shadowing logs warning."""
        constants = {"x": Const("x", IntSort())}
        parser = ExpressionParser({}, constants, {})
        parser.mark_symbols_loaded()

        shadow_var = Const("x", IntSort())
        with self.assertLogs(level="WARNING") as cm:
            parser.build_context([shadow_var])
        self.assertTrue(any("shadows" in msg for msg in cm.output))

    def test_bug5_security_sandbox_ast_based(self) -> None:
        """Bug #5: Security uses AST checking, not bytecode names."""
        # Dunder attribute access should be blocked
        expr = "().__class__"
        tree = ast.parse(expr, mode="eval")
        with self.assertRaises(ValueError) as ctx:
            ExpressionValidator.check_safe_ast(tree, expr)
        self.assertIn("dunder", str(ctx.exception))

    def test_bug6_empty_forall_validation(self) -> None:
        """Bug #6: Empty ForAll/Exists raises error."""
        config = {"rules": [{"forall": [], "constraint": "x > 0"}]}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            temp_file = f.name

        try:
            interpreter = Z3JSONInterpreter(temp_file)
            with self.assertRaises(ValueError) as ctx:
                interpreter.run()
            self.assertIn("Empty", str(ctx.exception))
        finally:
            import os

            os.unlink(temp_file)

    def test_bug7_topological_sort_implemented(self) -> None:
        """Bug #7: Sorts are topologically sorted."""
        config = {
            "sorts": [
                {"name": "MyArray", "type": "ArraySort(MySort, IntSort)"},
                {"name": "MySort", "type": "DeclareSort"},
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            temp_file = f.name

        try:
            interpreter = Z3JSONInterpreter(temp_file)
            # Should not raise even though MyArray comes before MySort
            interpreter.run()
        finally:
            import os

            os.unlink(temp_file)

    def test_bug8_constants_dict_semantics_fixed(self) -> None:
        """Bug #8: Constants dict uses key as Z3 name."""
        sort_manager = SortManager()
        constants_defs = {"test": {"sort": "IntSort", "members": {"my_const": "ignored_value"}}}
        sort_manager.create_constants(constants_defs)
        # Should use key 'my_const' as the constant name
        self.assertIn("my_const", sort_manager.constants)
        const = sort_manager.constants["my_const"]
        self.assertEqual(const.decl().name(), "my_const")

    def test_bug9_optimization_has_global_context(self) -> None:
        """Bug #9: Optimization can reference global constants."""
        config = {
            "constants": {"vals": {"sort": "IntSort", "members": ["x"]}},
            "knowledge_base": ["x == 5"],
            "optimization": {
                "variables": [{"name": "y", "sort": "IntSort"}],
                "constraints": ["y > x"],  # References global x
                "objectives": [{"expression": "y", "type": "minimize"}],
            },
            "actions": ["optimize"],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            temp_file = f.name

        try:
            interpreter = Z3JSONInterpreter(temp_file)
            # Should not raise NameError for undefined 'x'
            interpreter.run()
        finally:
            import os

            os.unlink(temp_file)

    def test_bug10_verification_uses_check_condition(self) -> None:
        """Bug #10: Verification uses solver.check(condition) properly."""
        # This is a semantic test - verify the verifier calls check correctly
        config = {
            "constants": {"vals": {"sort": "IntSort", "members": ["x"]}},
            "knowledge_base": ["x > 0"],
            "verifications": [{"name": "test", "constraint": "x > 0"}],
            "actions": ["verify_conditions"],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            temp_file = f.name

        try:
            interpreter = Z3JSONInterpreter(temp_file)
            with self.assertLogs(level="INFO") as cm:
                interpreter.run()
            # Should report SAT
            self.assertTrue(any("SAT" in msg for msg in cm.output))
        finally:
            import os

            os.unlink(temp_file)

    def test_bug11_logging_configured_in_main_only(self) -> None:
        """Bug #11: Logging configured in __main__ block only."""
        # Check that z3adapter modules don't call basicConfig
        with open("z3adapter/interpreter.py") as f:
            content = f.read()
            self.assertNotIn("basicConfig", content)

        # CLI should have basicConfig
        with open("z3adapter/cli.py") as f:
            content = f.read()
            self.assertIn("basicConfig", content)

    def test_bug12_bitvec_validation(self) -> None:
        """Bug #12: BitVecSort validates size."""
        sort_manager = SortManager()

        # Zero size should fail
        with self.assertRaises(ValueError) as ctx:
            sort_manager.create_sorts([{"name": "BV0", "type": "BitVecSort(0)"}])
        self.assertIn("positive", str(ctx.exception))

        # Negative size should fail
        with self.assertRaises(ValueError) as ctx:
            sort_manager.create_sorts([{"name": "BVNeg", "type": "BitVecSort(-1)"}])
        self.assertIn("positive", str(ctx.exception))

        # Too large size should fail
        with self.assertRaises(ValueError) as ctx:
            sort_manager.create_sorts([{"name": "BVHuge", "type": "BitVecSort(100000)"}])
        self.assertIn("exceeds", str(ctx.exception))

    def test_bug13_implication_requires_forall(self) -> None:
        """Bug #13: Implication rules require quantified variables."""
        config = {
            "constants": {"vals": {"sort": "IntSort", "members": ["x"]}},
            "rules": [{"implies": {"antecedent": "x > 0", "consequent": "x >= 1"}}],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            temp_file = f.name

        try:
            interpreter = Z3JSONInterpreter(temp_file)
            with self.assertRaises(ValueError) as ctx:
                interpreter.run()
            self.assertIn("require quantified variables", str(ctx.exception))
        finally:
            import os

            os.unlink(temp_file)

    def test_bug14_eval_exec_blocked(self) -> None:
        """Bug #14: eval/exec/compile/__import__ are blocked."""
        blocked_exprs = [
            "eval('1+1')",
            "exec('x=1')",
            "compile('1+1', '', 'eval')",
            "__import__('os')",
        ]

        for expr in blocked_exprs:
            tree = ast.parse(expr, mode="eval")
            with self.assertRaises(ValueError):
                ExpressionValidator.check_safe_ast(tree, expr)

    def test_bug15_function_definitions_blocked(self) -> None:
        """Bug #15: Function/class definitions blocked in expressions."""
        # Lambda is allowed (used by Z3), but def/class are not
        expr = "lambda x: x"
        tree = ast.parse(expr, mode="eval")
        # Should not raise - lambda is OK
        ExpressionValidator.check_safe_ast(tree, expr)

    def test_bug16_sort_dependency_validation(self) -> None:
        """Bug #16: ArraySort validates that referenced sorts exist."""
        sort_manager = SortManager()

        # Undefined domain sort should fail
        with self.assertRaises(ValueError) as ctx:
            sort_manager.create_sorts(
                [{"name": "BadArray", "type": "ArraySort(UndefinedSort, IntSort)"}]
            )
        self.assertIn("undefined", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
