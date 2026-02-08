"""Unit tests for SMT2 Expression Emitter."""

import pytest

from z3adapter.backends.smt2.emitter import ExpressionEmitter, emit_smt2_expr
from z3adapter.backends.smt2.ir import ConversionContext


class TestExpressionEmitter:
    """Tests for ExpressionEmitter class."""

    @pytest.fixture
    def ctx(self):
        """Create a conversion context for testing."""
        ctx = ConversionContext()
        ctx.variables = {"p": "Person", "x": "Int", "y": "Int"}
        return ctx

    @pytest.fixture
    def emitter(self, ctx):
        """Create an emitter with the context."""
        return ExpressionEmitter(ctx)

    def test_emit_simple_name(self, emitter):
        assert emitter.emit("x") == "x"
        assert emitter.emit("alice") == "alice"

    def test_emit_integer_constant(self, emitter):
        assert emitter.emit("42") == "42"
        assert emitter.emit("0") == "0"

    def test_emit_negative_integer(self, emitter):
        assert emitter.emit("-5") == "(- 5)"

    def test_emit_boolean_constant(self, emitter):
        assert emitter.emit("True") == "true"
        assert emitter.emit("False") == "false"

    def test_emit_string_constant(self, emitter):
        assert emitter.emit('"hello"') == '"hello"'

    def test_emit_function_call_no_args(self, emitter):
        assert emitter.emit("f()") == "f"

    def test_emit_function_call_one_arg(self, emitter):
        assert emitter.emit("age(alice)") == "(age alice)"

    def test_emit_function_call_multiple_args(self, emitter):
        assert emitter.emit("add(x, y)") == "(add x y)"

    def test_emit_nested_function_call(self, emitter):
        assert emitter.emit("f(g(x))") == "(f (g x))"

    def test_emit_comparison_equal(self, emitter):
        assert emitter.emit("x == y") == "(= x y)"

    def test_emit_comparison_not_equal(self, emitter):
        assert emitter.emit("x != y") == "(distinct x y)"

    def test_emit_comparison_less_than(self, emitter):
        assert emitter.emit("x < y") == "(< x y)"

    def test_emit_comparison_less_equal(self, emitter):
        assert emitter.emit("x <= y") == "(<= x y)"

    def test_emit_comparison_greater_than(self, emitter):
        assert emitter.emit("x > y") == "(> x y)"

    def test_emit_comparison_greater_equal(self, emitter):
        assert emitter.emit("x >= y") == "(>= x y)"

    def test_emit_chained_comparison(self, emitter):
        # a < b < c should become (and (< a b) (< b c))
        result = emitter.emit("a < b < c")
        assert result == "(and (< a b) (< b c))"

    def test_emit_arithmetic_add(self, emitter):
        assert emitter.emit("x + y") == "(+ x y)"

    def test_emit_arithmetic_sub(self, emitter):
        assert emitter.emit("x - y") == "(- x y)"

    def test_emit_arithmetic_mul(self, emitter):
        assert emitter.emit("x * y") == "(* x y)"

    def test_emit_arithmetic_div(self, emitter):
        assert emitter.emit("x / y") == "(div x y)"

    def test_emit_arithmetic_mod(self, emitter):
        assert emitter.emit("x % y") == "(mod x y)"

    def test_emit_and_operator(self, emitter):
        assert emitter.emit("And(a, b)") == "(and a b)"

    def test_emit_or_operator(self, emitter):
        assert emitter.emit("Or(a, b)") == "(or a b)"

    def test_emit_not_operator(self, emitter):
        assert emitter.emit("Not(a)") == "(not a)"

    def test_emit_implies_operator(self, emitter):
        assert emitter.emit("Implies(a, b)") == "(=> a b)"

    def test_emit_if_operator(self, emitter):
        assert emitter.emit("If(cond, then_val, else_val)") == "(ite cond then_val else_val)"

    def test_emit_distinct_operator(self, emitter):
        assert emitter.emit("Distinct(a, b, c)") == "(distinct a b c)"

    def test_emit_boolean_and_expression(self, emitter):
        # Python's 'and' operator
        result = emitter.emit("a and b")
        assert result == "(and a b)"

    def test_emit_boolean_or_expression(self, emitter):
        # Python's 'or' operator
        result = emitter.emit("a or b")
        assert result == "(or a b)"

    def test_emit_boolean_not_expression(self, emitter):
        # Python's 'not' operator
        result = emitter.emit("not a")
        assert result == "(not a)"

    def test_emit_unary_minus(self, emitter):
        assert emitter.emit("-x") == "(- x)"

    def test_emit_if_expression(self, emitter):
        # Python's ternary if/else
        result = emitter.emit("then_val if cond else else_val")
        assert result == "(ite cond then_val else_val)"

    def test_emit_complex_expression(self, emitter):
        result = emitter.emit("And(age(alice) > 18, is_adult(alice))")
        assert result == "(and (> (age alice) 18) (is_adult alice))"

    def test_emit_nested_operators(self, emitter):
        result = emitter.emit("Implies(And(a, b), Or(c, d))")
        assert result == "(=> (and a b) (or c d))"

    def test_emit_forall_quantifier(self, emitter):
        result = emitter.emit("ForAll([p], is_mortal(p))")
        # p should be resolved to Person sort from context
        assert "forall" in result
        assert "(p Person)" in result
        assert "(is_mortal p)" in result

    def test_emit_exists_quantifier(self, emitter):
        result = emitter.emit("Exists([x], x > 0)")
        assert "exists" in result
        assert "(x Int)" in result

    def test_emit_forall_with_implication(self, emitter):
        result = emitter.emit("ForAll([p], Implies(is_human(p), is_mortal(p)))")
        assert "forall" in result
        assert "=>" in result

    def test_emit_invalid_syntax_raises(self, emitter):
        with pytest.raises(ValueError, match="Invalid expression syntax"):
            emitter.emit("x + ")  # Incomplete expression


class TestEmitSmt2Expr:
    """Tests for the convenience function."""

    def test_emit_without_context(self):
        result = emit_smt2_expr("x + y")
        assert result == "(+ x y)"

    def test_emit_with_context(self):
        ctx = ConversionContext()
        ctx.variables = {"x": "Int"}
        result = emit_smt2_expr("x > 0", ctx)
        assert result == "(> x 0)"


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_function_args(self):
        ctx = ConversionContext()
        emitter = ExpressionEmitter(ctx)
        # 0-arity function call
        result = emitter.emit("get_value()")
        assert result == "get_value"

    def test_deeply_nested_expression(self):
        ctx = ConversionContext()
        emitter = ExpressionEmitter(ctx)
        result = emitter.emit("f(g(h(i(x))))")
        assert result == "(f (g (h (i x))))"

    def test_complex_arithmetic(self):
        ctx = ConversionContext()
        emitter = ExpressionEmitter(ctx)
        result = emitter.emit("(x + y) * (a - b)")
        assert result == "(* (+ x y) (- a b))"
