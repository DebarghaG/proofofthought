"""Unit tests for security validator."""

import ast
import unittest

from z3adapter.security.validator import ExpressionValidator


class TestExpressionValidator(unittest.TestCase):
    """Test cases for ExpressionValidator security checks."""

    def test_check_safe_ast_allows_valid_expression(self) -> None:
        """Test that valid expressions are allowed."""
        expr = "x + y * 2"
        tree = ast.parse(expr, mode="eval")
        # Should not raise
        ExpressionValidator.check_safe_ast(tree, expr)

    def test_check_safe_ast_blocks_dunder_attributes(self) -> None:
        """Test that dunder attribute access is blocked."""
        expr = "obj.__class__"
        tree = ast.parse(expr, mode="eval")
        with self.assertRaises(ValueError) as ctx:
            ExpressionValidator.check_safe_ast(tree, expr)
        self.assertIn("dunder attribute", str(ctx.exception))
        self.assertIn("__class__", str(ctx.exception))

    def test_check_safe_ast_blocks_dunder_in_nested_expression(self) -> None:
        """Test that nested dunder access is caught."""
        expr = "foo.bar.__bases__"
        tree = ast.parse(expr, mode="eval")
        with self.assertRaises(ValueError) as ctx:
            ExpressionValidator.check_safe_ast(tree, expr)
        self.assertIn("__bases__", str(ctx.exception))

    def test_check_safe_ast_blocks_import(self) -> None:
        """Test that import statements are blocked."""
        # This will fail to parse in eval mode, but test Import node check
        with self.assertRaises(SyntaxError):
            ast.parse("import os", mode="eval")

    def test_check_safe_ast_blocks_eval_call(self) -> None:
        """Test that eval() calls are blocked."""
        expr = "eval('1+1')"
        tree = ast.parse(expr, mode="eval")
        with self.assertRaises(ValueError) as ctx:
            ExpressionValidator.check_safe_ast(tree, expr)
        self.assertIn("eval", str(ctx.exception))

    def test_check_safe_ast_blocks_exec_call(self) -> None:
        """Test that exec() calls are blocked."""
        expr = "exec('x=1')"
        tree = ast.parse(expr, mode="eval")
        with self.assertRaises(ValueError) as ctx:
            ExpressionValidator.check_safe_ast(tree, expr)
        self.assertIn("exec", str(ctx.exception))

    def test_check_safe_ast_blocks_compile_call(self) -> None:
        """Test that compile() calls are blocked."""
        expr = "compile('1+1', '', 'eval')"
        tree = ast.parse(expr, mode="eval")
        with self.assertRaises(ValueError) as ctx:
            ExpressionValidator.check_safe_ast(tree, expr)
        self.assertIn("compile", str(ctx.exception))

    def test_check_safe_ast_blocks_import_call(self) -> None:
        """Test that __import__() calls are blocked."""
        expr = "__import__('os')"
        tree = ast.parse(expr, mode="eval")
        with self.assertRaises(ValueError) as ctx:
            ExpressionValidator.check_safe_ast(tree, expr)
        self.assertIn("__import__", str(ctx.exception))

    def test_safe_eval_evaluates_simple_expression(self) -> None:
        """Test that simple expressions evaluate correctly."""
        expr = "2 + 3"
        result = ExpressionValidator.safe_eval(expr, {}, {})
        self.assertEqual(result, 5)

    def test_safe_eval_uses_context(self) -> None:
        """Test that context variables are accessible."""
        expr = "x + y"
        context = {"x": 10, "y": 20}
        result = ExpressionValidator.safe_eval(expr, {}, context)
        self.assertEqual(result, 30)

    def test_safe_eval_uses_safe_globals(self) -> None:
        """Test that safe globals are accessible."""
        from z3 import And, BoolVal

        expr = "And(a, b)"
        safe_globals = {"And": And}
        context = {"a": BoolVal(True), "b": BoolVal(False)}
        result = ExpressionValidator.safe_eval(expr, safe_globals, context)
        self.assertIsNotNone(result)

    def test_safe_eval_blocks_builtins(self) -> None:
        """Test that builtins are not accessible."""
        expr = "open('/etc/passwd')"
        with self.assertRaises(ValueError):
            ExpressionValidator.safe_eval(expr, {}, {})

    def test_safe_eval_handles_syntax_error(self) -> None:
        """Test that syntax errors are caught and wrapped."""
        expr = "2 +"
        with self.assertRaises(ValueError) as ctx:
            ExpressionValidator.safe_eval(expr, {}, {})
        self.assertIn("Syntax error", str(ctx.exception))

    def test_safe_eval_handles_name_error(self) -> None:
        """Test that undefined names raise appropriate error."""
        expr = "undefined_variable"
        with self.assertRaises(ValueError) as ctx:
            ExpressionValidator.safe_eval(expr, {}, {})
        self.assertIn("Undefined name", str(ctx.exception))

    def test_safe_eval_prevents_getattr_exploit(self) -> None:
        """Test that getattr can't be used to access dunder methods."""
        # Even though we allow getattr in safe_globals, dunder access in AST is blocked
        expr = "().__class__"
        tree = ast.parse(expr, mode="eval")
        with self.assertRaises(ValueError):
            ExpressionValidator.check_safe_ast(tree, expr)

    def test_safe_eval_allows_normal_attribute_access(self) -> None:
        """Test that normal attribute access is allowed."""

        class Obj:
            value = 42

        expr = "obj.value"
        context = {"obj": Obj()}
        result = ExpressionValidator.safe_eval(expr, {}, context)
        self.assertEqual(result, 42)

    def test_check_safe_ast_allows_lambda(self) -> None:
        """Test that lambda expressions are allowed (used by Z3)."""
        expr = "lambda x: x + 1"
        tree = ast.parse(expr, mode="eval")
        # Should not raise
        ExpressionValidator.check_safe_ast(tree, expr)

    def test_check_safe_ast_allows_list_comprehension(self) -> None:
        """Test that list comprehensions are allowed."""
        expr = "[x * 2 for x in range(5)]"
        tree = ast.parse(expr, mode="eval")
        # Should not raise
        ExpressionValidator.check_safe_ast(tree, expr)


if __name__ == "__main__":
    unittest.main()
