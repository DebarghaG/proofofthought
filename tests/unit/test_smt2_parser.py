"""Unit tests for SMT2 Output Parser."""

import pytest

from z3adapter.backends.smt2.parser import (
    ExecutionResult,
    ModelValue,
    SMTQueryResult,
    Z3OutputParser,
)


class TestSMTQueryResult:
    """Tests for SMTQueryResult dataclass."""

    def test_create_sat_result(self):
        result = SMTQueryResult(
            query_id="query_0",
            query_name="check_positive",
            status="sat",
            model=[ModelValue(name="x", sort="Int", value="42")],
        )
        assert result.status == "sat"
        assert len(result.model) == 1
        assert result.model[0].value == "42"

    def test_create_unsat_result(self):
        result = SMTQueryResult(
            query_id="query_0",
            query_name="check_impossible",
            status="unsat",
        )
        assert result.status == "unsat"
        assert len(result.model) == 0


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_answer_sat_only(self):
        result = ExecutionResult(
            success=True,
            sat_count=2,
            unsat_count=0,
        )
        assert result.answer is True

    def test_answer_unsat_only(self):
        result = ExecutionResult(
            success=True,
            sat_count=0,
            unsat_count=2,
        )
        assert result.answer is False

    def test_answer_mixed(self):
        result = ExecutionResult(
            success=True,
            sat_count=1,
            unsat_count=1,
        )
        assert result.answer is None

    def test_answer_none(self):
        result = ExecutionResult(
            success=True,
            sat_count=0,
            unsat_count=0,
        )
        assert result.answer is None


class TestZ3OutputParser:
    """Tests for Z3OutputParser class."""

    @pytest.fixture
    def parser(self):
        return Z3OutputParser()

    def test_parse_simple_sat(self, parser):
        output = "sat"
        result = parser.parse(output)
        assert result.success is True
        assert result.sat_count == 1
        assert result.unsat_count == 0
        assert result.answer is True

    def test_parse_simple_unsat(self, parser):
        output = "unsat"
        result = parser.parse(output)
        assert result.success is True
        assert result.sat_count == 0
        assert result.unsat_count == 1
        assert result.answer is False

    def test_parse_unknown(self, parser):
        output = "unknown"
        result = parser.parse(output)
        assert result.unknown_count == 1

    def test_parse_with_model(self, parser):
        output = """sat
(model
  (define-fun x () Int 42)
  (define-fun y () Int 10)
)"""
        result = parser.parse(output)
        assert result.sat_count == 1
        assert len(result.queries) == 1
        assert len(result.queries[0].model) == 2

    def test_parse_multiple_queries(self, parser):
        output = """sat
(model
  (define-fun x () Int 1)
)
unsat
sat
(model
  (define-fun y () Int 2)
)"""
        result = parser.parse(output, ["q1", "q2", "q3"])
        assert result.sat_count == 2
        assert result.unsat_count == 1
        assert len(result.queries) == 3
        assert result.queries[0].query_name == "q1"
        assert result.queries[0].status == "sat"
        assert result.queries[1].query_name == "q2"
        assert result.queries[1].status == "unsat"

    def test_parse_empty_output(self, parser):
        output = ""
        result = parser.parse(output)
        assert result.success is False
        assert result.error == "No query results parsed from Z3 output"
        assert result.sat_count == 0
        assert result.unsat_count == 0

    def test_parse_with_errors(self, parser):
        output = """(error "line 5: unknown sort 'Foo'")
unsat"""
        result = parser.parse(output)
        assert result.unsat_count == 1
        assert result.success is False
        assert result.non_model_errors == ['(error "line 5: unknown sort \'Foo\'")']

    def test_parse_model_unavailable_error_is_nonfatal(self, parser):
        output = """unsat
(error "line 8 column 10: model is not available")"""
        result = parser.parse(output)
        assert result.unsat_count == 1
        assert result.success is True
        assert result.non_model_errors == []
        assert result.model_errors == ['(error "line 8 column 10: model is not available")']

    def test_parse_case_insensitive(self, parser):
        output = "SAT"
        result = parser.parse(output)
        assert result.sat_count == 1

        output2 = "UNSAT"
        result2 = parser.parse(output2)
        assert result2.unsat_count == 1

    def test_parse_sat_not_in_unsat(self, parser):
        # Make sure "sat" doesn't match the "sat" in "unsat"
        output = "unsat"
        result = parser.parse(output)
        assert result.sat_count == 0
        assert result.unsat_count == 1

    def test_parse_simple_counts(self, parser):
        sat_count, unsat_count = parser.parse_simple("sat\nsat\nunsat")
        assert sat_count == 2
        assert unsat_count == 1

    def test_parse_model_values(self, parser):
        output = """sat
(model
  (define-fun alice () Person alice_val)
  (define-fun age () Int 30)
)"""
        result = parser.parse(output)
        query = result.queries[0]
        assert len(query.model) == 2

        alice_model = next(m for m in query.model if m.name == "alice")
        assert alice_model.sort == "Person"
        assert alice_model.value == "alice_val"

        age_model = next(m for m in query.model if m.name == "age")
        assert age_model.sort == "Int"
        assert age_model.value == "30"

    def test_parse_timeout(self, parser):
        output = "timeout"
        result = parser.parse(output)
        assert result.unknown_count == 1
        assert result.queries[0].status == "timeout"


class TestModelValue:
    """Tests for ModelValue dataclass."""

    def test_create_int_value(self):
        val = ModelValue(name="x", sort="Int", value="42")
        assert val.name == "x"
        assert val.sort == "Int"
        assert val.value == "42"

    def test_create_bool_value(self):
        val = ModelValue(name="flag", sort="Bool", value="true")
        assert val.value == "true"


class TestEdgeCases:
    """Tests for edge cases in parsing."""

    @pytest.fixture
    def parser(self):
        return Z3OutputParser()

    def test_whitespace_handling(self, parser):
        output = """

        sat

        """
        result = parser.parse(output)
        assert result.sat_count == 1

    def test_multiple_sat_in_same_line(self, parser):
        # Unusual but possible
        output = "sat sat"
        result = parser.parse(output)
        # Should count each occurrence
        assert result.sat_count >= 1

    def test_model_with_complex_value(self, parser):
        output = """sat
(model
  (define-fun arr () (Array Int Int) ((as const (Array Int Int)) 0))
)"""
        result = parser.parse(output)
        assert result.sat_count == 1
