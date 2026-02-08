"""Unit tests for SMT2 Intermediate Representation."""

import pytest

from z3adapter.backends.smt2.ir import (
    ConversionContext,
    SMTAssertion,
    SMTConstant,
    SMTFunction,
    SMTQuery,
    SMTSort,
    SMTSortKind,
)


class TestSMTSort:
    """Tests for SMTSort dataclass."""

    def test_create_uninterpreted_sort(self):
        sort = SMTSort(
            name="Person",
            kind=SMTSortKind.UNINTERPRETED,
            smt_name="Person",
            smt_code="(declare-sort Person 0)",
        )
        assert sort.name == "Person"
        assert sort.kind == SMTSortKind.UNINTERPRETED
        assert sort.emitted is False

    def test_create_enum_sort(self):
        sort = SMTSort(
            name="Color",
            kind=SMTSortKind.ENUM,
            smt_name="Color",
            params={"values": ["red", "green", "blue"]},
        )
        assert sort.name == "Color"
        assert sort.params["values"] == ["red", "green", "blue"]

    def test_create_bitvec_sort(self):
        sort = SMTSort(
            name="BV32",
            kind=SMTSortKind.BITVEC,
            smt_name="(_ BitVec 32)",
            params={"size": 32},
        )
        assert sort.params["size"] == 32

    def test_create_array_sort(self):
        sort = SMTSort(
            name="IntArray",
            kind=SMTSortKind.ARRAY,
            smt_name="(Array Int Int)",
            params={"domain": "Int", "range": "Int"},
        )
        assert sort.params["domain"] == "Int"


class TestSMTFunction:
    """Tests for SMTFunction dataclass."""

    def test_create_predicate(self):
        func = SMTFunction(
            name="is_adult",
            smt_name="is_adult",
            domain=["Person"],
            range_sort="Bool",
            smt_code="(declare-fun is_adult (Person) Bool)",
        )
        assert func.name == "is_adult"
        assert func.domain == ["Person"]
        assert func.range_sort == "Bool"

    def test_create_function(self):
        func = SMTFunction(
            name="age",
            smt_name="age",
            domain=["Person"],
            range_sort="Int",
        )
        assert func.range_sort == "Int"


class TestConversionContext:
    """Tests for ConversionContext."""

    def test_empty_context(self):
        ctx = ConversionContext()
        assert ctx.logic == "ALL"
        assert len(ctx.sorts) == 0
        assert len(ctx.functions) == 0
        assert len(ctx.constants) == 0

    def test_has_sort_builtin(self):
        ctx = ConversionContext()
        assert ctx.has_sort("Bool")
        assert ctx.has_sort("Int")
        assert ctx.has_sort("Real")
        assert ctx.has_sort("BoolSort")
        assert ctx.has_sort("IntSort")
        assert ctx.has_sort("RealSort")

    def test_has_sort_custom(self):
        ctx = ConversionContext()
        ctx.sorts["Person"] = SMTSort(
            name="Person", kind=SMTSortKind.UNINTERPRETED, smt_name="Person"
        )
        assert ctx.has_sort("Person")
        assert not ctx.has_sort("Animal")

    def test_resolve_sort_name_builtin(self):
        ctx = ConversionContext()
        assert ctx.resolve_sort_name("BoolSort") == "Bool"
        assert ctx.resolve_sort_name("IntSort") == "Int"
        assert ctx.resolve_sort_name("RealSort") == "Real"
        assert ctx.resolve_sort_name("Int") == "Int"

    def test_resolve_sort_name_custom(self):
        ctx = ConversionContext()
        ctx.sorts["Person"] = SMTSort(
            name="Person", kind=SMTSortKind.UNINTERPRETED, smt_name="Person"
        )
        assert ctx.resolve_sort_name("Person") == "Person"

    def test_get_unemitted(self):
        ctx = ConversionContext()
        ctx.sorts["Person"] = SMTSort(
            name="Person", kind=SMTSortKind.UNINTERPRETED, smt_name="Person", emitted=False
        )
        ctx.functions["age"] = SMTFunction(
            name="age", smt_name="age", emitted=True
        )

        unemitted = ctx.get_unemitted()
        assert "sort:Person" in unemitted
        assert "func:age" not in unemitted

    def test_to_summary(self):
        ctx = ConversionContext()
        ctx.sorts["Person"] = SMTSort(
            name="Person", kind=SMTSortKind.UNINTERPRETED, smt_name="Person"
        )
        ctx.functions["age"] = SMTFunction(
            name="age", smt_name="age"
        )
        ctx.constants["alice"] = SMTConstant(
            name="alice", smt_name="alice", sort="Person"
        )

        summary = ctx.to_summary()
        assert "; Logic: ALL" in summary
        assert "Person" in summary
        assert "age" in summary
        assert "alice" in summary

    def test_to_dict(self):
        ctx = ConversionContext()
        ctx.sorts["Person"] = SMTSort(
            name="Person", kind=SMTSortKind.UNINTERPRETED, smt_name="Person"
        )

        d = ctx.to_dict()
        assert d["logic"] == "ALL"
        assert "Person" in d["sorts"]
        assert d["sorts"]["Person"]["kind"] == "uninterpreted"


class TestSMTAssertion:
    """Tests for SMTAssertion dataclass."""

    def test_create_assertion(self):
        assertion = SMTAssertion(
            id="kb_0",
            dsl_expr="age(alice) > 18",
            smt_expr="(> (age alice) 18)",
            smt_code="(assert (> (age alice) 18))",
        )
        assert assertion.id == "kb_0"
        assert assertion.label is None
        assert assertion.emitted is False

    def test_create_labeled_assertion(self):
        assertion = SMTAssertion(
            id="scenario_0",
            dsl_expr="check_adult",
            smt_expr="(is_adult alice)",
            label="check_alice_adult",
        )
        assert assertion.label == "check_alice_adult"


class TestSMTQuery:
    """Tests for SMTQuery dataclass."""

    def test_create_query(self):
        query = SMTQuery(
            id="query_0",
            name="check_adult",
            assertions=["scenario_0"],
            check_model=True,
        )
        assert query.id == "query_0"
        assert query.name == "check_adult"
        assert query.assertions == ["scenario_0"]
        assert query.check_model is True
        assert query.emitted is False
