"""Expression emitter for converting DSL expressions to SMT-LIB."""

from __future__ import annotations

import ast
import logging
import re
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from z3adapter.backends.smt2.ir import ConversionContext


class ExpressionEmitter:
    """
    Converts DSL expressions (Python-like) to SMT-LIB S-expressions.

    Handles:
    - Function application: f(x, y) -> (f x y)
    - Operators: And(a, b) -> (and a b)
    - Comparisons: x > y -> (> x y)
    - Quantifiers: ForAll([x], expr) -> (forall ((x Sort)) expr)
    """

    # Mapping of DSL operators to SMT-LIB
    OPERATOR_MAP = {
        "And": "and",
        "Or": "or",
        "Not": "not",
        "Implies": "=>",
        "If": "ite",
        "Distinct": "distinct",
    }

    # Comparison operators
    COMPARISON_OPS = {
        ast.Eq: "=",
        ast.NotEq: "distinct",  # SMT-LIB uses distinct for !=
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
    }

    # Arithmetic operators
    ARITH_OPS = {
        ast.Add: "+",
        ast.Sub: "-",
        ast.Mult: "*",
        ast.Div: "div",
        ast.Mod: "mod",
    }

    def __init__(self, ctx: ConversionContext) -> None:
        self.ctx = ctx

    def emit(self, expr_str: str) -> str:
        """
        Convert DSL expression string to SMT-LIB.

        Args:
            expr_str: DSL expression (Python-like syntax)

        Returns:
            SMT-LIB S-expression string
        """
        try:
            tree = ast.parse(expr_str, mode="eval")
            return self._emit_node(tree.body)
        except SyntaxError as e:
            raise ValueError(f"Invalid expression syntax: {expr_str}") from e

    def _emit_node(self, node: ast.AST) -> str:
        """Recursively emit AST node to SMT-LIB."""
        if isinstance(node, ast.Name):
            return node.id

        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return "true" if node.value else "false"
            elif isinstance(node.value, int):
                if node.value < 0:
                    return f"(- {abs(node.value)})"
                return str(node.value)
            elif isinstance(node.value, float):
                return str(node.value)
            elif isinstance(node.value, str):
                return f'"{node.value}"'
            else:
                return str(node.value)

        elif isinstance(node, ast.Call):
            func_name = self._get_func_name(node.func)

            # Handle quantifiers specially
            if func_name in ("ForAll", "Exists"):
                return self._emit_quantifier(func_name, node)

            args = [self._emit_node(arg) for arg in node.args]

            # Handle special operators
            if func_name in self.OPERATOR_MAP:
                smt_op = self.OPERATOR_MAP[func_name]
                return f"({smt_op} {' '.join(args)})"
            else:
                # Regular function application
                if args:
                    return f"({func_name} {' '.join(args)})"
                else:
                    return func_name

        elif isinstance(node, ast.Compare):
            # Handle chained comparisons: a < b < c -> (and (< a b) (< b c))
            left = self._emit_node(node.left)
            comparisons = []
            prev = left

            for op, comparator in zip(node.ops, node.comparators):
                right = self._emit_node(comparator)
                smt_op = self.COMPARISON_OPS.get(type(op))
                if smt_op:
                    comparisons.append(f"({smt_op} {prev} {right})")
                prev = right

            if len(comparisons) == 1:
                return comparisons[0]
            else:
                return f"(and {' '.join(comparisons)})"

        elif isinstance(node, ast.BinOp):
            left = self._emit_node(node.left)
            right = self._emit_node(node.right)
            smt_op = self.ARITH_OPS.get(type(node.op))
            if smt_op:
                return f"({smt_op} {left} {right})"
            else:
                raise ValueError(f"Unsupported binary operator: {type(node.op)}")

        elif isinstance(node, ast.UnaryOp):
            operand = self._emit_node(node.operand)
            if isinstance(node.op, ast.Not):
                return f"(not {operand})"
            elif isinstance(node.op, ast.USub):
                return f"(- {operand})"
            else:
                raise ValueError(f"Unsupported unary operator: {type(node.op)}")

        elif isinstance(node, ast.BoolOp):
            values = [self._emit_node(v) for v in node.values]
            if isinstance(node.op, ast.And):
                return f"(and {' '.join(values)})"
            elif isinstance(node.op, ast.Or):
                return f"(or {' '.join(values)})"
            else:
                raise ValueError(f"Unsupported boolean operator: {type(node.op)}")

        elif isinstance(node, ast.IfExp):
            test = self._emit_node(node.test)
            body = self._emit_node(node.body)
            orelse = self._emit_node(node.orelse)
            return f"(ite {test} {body} {orelse})"

        elif isinstance(node, ast.Subscript):
            # Handle array access: arr[idx] -> (select arr idx)
            value = self._emit_node(node.value)
            idx = self._emit_node(node.slice)
            return f"(select {value} {idx})"

        elif isinstance(node, ast.List):
            # Handle list of variable names for quantifiers
            return [self._emit_node(elt) for elt in node.elts]

        elif isinstance(node, ast.Tuple):
            # Handle tuple (treat as list)
            return [self._emit_node(elt) for elt in node.elts]

        else:
            raise ValueError(f"Unsupported AST node type: {type(node).__name__}")

    def _emit_quantifier(self, quantifier: str, node: ast.Call) -> str:
        """Emit a quantifier expression (ForAll or Exists)."""
        if len(node.args) < 2:
            raise ValueError(f"{quantifier} requires at least 2 arguments: variables and body")

        # First argument is the list of bound variables
        var_list = node.args[0]
        if isinstance(var_list, ast.List):
            var_names = [self._emit_node(v) for v in var_list.elts]
        else:
            var_names = [self._emit_node(var_list)]

        # Build variable bindings with sorts from context
        var_bindings = []
        for var_name in var_names:
            # Look up variable sort in context
            if var_name in self.ctx.variables:
                sort_name = self.ctx.variables[var_name]
                smt_sort = self.ctx.resolve_sort_name(sort_name)
            else:
                logger.warning(
                    f"Quantifier variable '{var_name}' not found in context variables. "
                    f"Defaulting to Int. Register variables via VariablesStage or "
                    f"config['variables'] to ensure correct sort binding."
                )
                smt_sort = "Int"
            var_bindings.append(f"({var_name} {smt_sort})")

        bindings_str = " ".join(var_bindings)

        # Second argument is the body expression
        body = self._emit_node(node.args[1])

        smt_quantifier = "forall" if quantifier == "ForAll" else "exists"
        return f"({smt_quantifier} ({bindings_str}) {body})"

    def _get_func_name(self, node: ast.AST) -> str:
        """Extract function name from call node."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_func_name(node.value)}.{node.attr}"
        else:
            raise ValueError(f"Cannot extract function name from: {type(node).__name__}")


def emit_smt2_expr(expr_str: str, ctx: ConversionContext | None = None) -> str:
    """
    Convenience function to emit a single expression.

    Args:
        expr_str: DSL expression string
        ctx: Optional conversion context

    Returns:
        SMT-LIB S-expression string
    """
    from z3adapter.backends.smt2.ir import ConversionContext

    if ctx is None:
        ctx = ConversionContext()
    emitter = ExpressionEmitter(ctx)
    return emitter.emit(expr_str)
