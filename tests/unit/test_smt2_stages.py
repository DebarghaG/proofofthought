"""Unit tests for SMT2 Pipeline Stages."""

import pytest

from z3adapter.backends.smt2.ir import ConversionContext, SMTSortKind
from z3adapter.backends.smt2.stages import (
    ConstantsStage,
    FunctionsStage,
    KnowledgeBaseStage,
    LogicStage,
    Pipeline,
    RulesStage,
    SortsStage,
    VariablesStage,
    VerificationsStage,
)


class TestLogicStage:
    """Tests for LogicStage."""

    def test_default_logic(self):
        ctx = ConversionContext()
        stage = LogicStage()
        result = stage.process(ctx, {})
        assert result == "(set-logic ALL)\n"
        assert ctx.logic == "ALL"

    def test_custom_logic(self):
        ctx = ConversionContext()
        stage = LogicStage()
        result = stage.process(ctx, {"logic": "QF_LIA"})
        assert result == "(set-logic QF_LIA)\n"
        assert ctx.logic == "QF_LIA"


class TestSortsStage:
    """Tests for SortsStage."""

    def test_empty_sorts(self):
        ctx = ConversionContext()
        stage = SortsStage()
        result = stage.process(ctx, {"sorts": []})
        assert result == ""

    def test_declare_sort(self):
        ctx = ConversionContext()
        stage = SortsStage()
        result = stage.process(ctx, {"sorts": [{"name": "Person", "type": "DeclareSort"}]})
        assert "(declare-sort Person 0)" in result
        assert "Person" in ctx.sorts
        assert ctx.sorts["Person"].kind == SMTSortKind.UNINTERPRETED

    def test_enum_sort(self):
        ctx = ConversionContext()
        stage = SortsStage()
        result = stage.process(
            ctx,
            {"sorts": [{"name": "Color", "type": "EnumSort", "values": ["red", "green", "blue"]}]},
        )
        assert "declare-datatypes" in result
        assert "(red)" in result
        assert "(green)" in result
        assert "(blue)" in result
        assert ctx.sorts["Color"].params["values"] == ["red", "green", "blue"]

    def test_bitvec_sort(self):
        ctx = ConversionContext()
        stage = SortsStage()
        stage.process(ctx, {"sorts": [{"name": "BV32", "type": "BitVecSort(32)"}]})
        # BitVec doesn't need declaration but should be registered
        assert "BV32" in ctx.sorts
        assert ctx.sorts["BV32"].smt_name == "(_ BitVec 32)"

    def test_array_sort(self):
        ctx = ConversionContext()
        stage = SortsStage()
        stage.process(ctx, {"sorts": [{"name": "IntArray", "type": "ArraySort(Int, Int)"}]})
        assert "IntArray" in ctx.sorts
        assert ctx.sorts["IntArray"].smt_name == "(Array Int Int)"

    def test_topological_sort(self):
        ctx = ConversionContext()
        stage = SortsStage()
        # PersonArray depends on Person
        result = stage.process(
            ctx,
            {
                "sorts": [
                    {"name": "PersonArray", "type": "ArraySort(Person, Int)"},
                    {"name": "Person", "type": "DeclareSort"},
                ]
            },
        )
        # Person should be declared before PersonArray
        person_pos = result.find("declare-sort Person")
        assert person_pos != -1
        assert "Person" in ctx.sorts


class TestFunctionsStage:
    """Tests for FunctionsStage."""

    def test_empty_functions(self):
        ctx = ConversionContext()
        stage = FunctionsStage()
        result = stage.process(ctx, {"functions": []})
        assert result == ""

    def test_predicate_function(self):
        ctx = ConversionContext()
        stage = FunctionsStage()
        result = stage.process(
            ctx, {"functions": [{"name": "is_adult", "domain": ["Person"], "range": "BoolSort"}]}
        )
        assert "(declare-fun is_adult (Person) Bool)" in result
        assert "is_adult" in ctx.functions

    def test_function_multiple_args(self):
        ctx = ConversionContext()
        stage = FunctionsStage()
        result = stage.process(
            ctx,
            {"functions": [{"name": "add", "domain": ["IntSort", "IntSort"], "range": "IntSort"}]},
        )
        assert "(declare-fun add (Int Int) Int)" in result

    def test_function_no_args(self):
        ctx = ConversionContext()
        stage = FunctionsStage()
        result = stage.process(
            ctx, {"functions": [{"name": "get_count", "domain": [], "range": "IntSort"}]}
        )
        assert "(declare-fun get_count () Int)" in result


class TestConstantsStage:
    """Tests for ConstantsStage."""

    def test_empty_constants(self):
        ctx = ConversionContext()
        stage = ConstantsStage()
        result = stage.process(ctx, {"constants": {}})
        assert result == ""

    def test_list_constants(self):
        ctx = ConversionContext()
        stage = ConstantsStage()
        result = stage.process(
            ctx, {"constants": {"people": {"sort": "Person", "members": ["alice", "bob"]}}}
        )
        assert "(declare-const alice Person)" in result
        assert "(declare-const bob Person)" in result
        assert "alice" in ctx.constants
        assert "bob" in ctx.constants

    def test_dict_constants(self):
        ctx = ConversionContext()
        stage = ConstantsStage()
        result = stage.process(
            ctx,
            {
                "constants": {
                    "people": {"sort": "Person", "members": {"alice": "alice", "bob": "bob"}}
                }
            },
        )
        assert "(declare-const alice Person)" in result
        assert "alice" in ctx.constants


class TestVariablesStage:
    """Tests for VariablesStage."""

    def test_empty_variables(self):
        ctx = ConversionContext()
        stage = VariablesStage()
        result = stage.process(ctx, {"variables": []})
        assert result == ""

    def test_register_variables(self):
        ctx = ConversionContext()
        stage = VariablesStage()
        result = stage.process(
            ctx,
            {
                "variables": [
                    {"name": "p", "sort": "Person"},
                    {"name": "x", "sort": "IntSort"},
                ]
            },
        )
        assert ctx.variables["p"] == "Person"
        assert ctx.variables["x"] == "IntSort"
        # Variables should be in comment
        assert "p" in result
        assert "x" in result


class TestKnowledgeBaseStage:
    """Tests for KnowledgeBaseStage."""

    def test_empty_kb(self):
        ctx = ConversionContext()
        stage = KnowledgeBaseStage()
        result = stage.process(ctx, {"knowledge_base": []})
        assert result == ""

    def test_simple_assertion(self):
        ctx = ConversionContext()
        stage = KnowledgeBaseStage()
        result = stage.process(ctx, {"knowledge_base": ["x > 0"]})
        assert "(assert (> x 0))" in result
        assert "kb_0" in ctx.kb_assertions

    def test_dict_assertion_true(self):
        ctx = ConversionContext()
        stage = KnowledgeBaseStage()
        result = stage.process(
            ctx, {"knowledge_base": [{"assertion": "is_adult(alice)", "value": True}]}
        )
        assert "(assert (is_adult alice))" in result

    def test_dict_assertion_false(self):
        ctx = ConversionContext()
        stage = KnowledgeBaseStage()
        result = stage.process(
            ctx, {"knowledge_base": [{"assertion": "is_adult(bob)", "value": False}]}
        )
        assert "(assert (not (is_adult bob)))" in result

    def test_multiple_assertions(self):
        ctx = ConversionContext()
        stage = KnowledgeBaseStage()
        result = stage.process(ctx, {"knowledge_base": ["x > 0", "y < 10"]})
        assert "(assert (> x 0))" in result
        assert "(assert (< y 10))" in result
        assert len(ctx.kb_assertions) == 2


class TestRulesStage:
    """Tests for RulesStage."""

    def test_empty_rules(self):
        ctx = ConversionContext()
        stage = RulesStage()
        result = stage.process(ctx, {"rules": []})
        assert result == ""

    def test_forall_implies_rule(self):
        ctx = ConversionContext()
        stage = RulesStage()
        result = stage.process(
            ctx,
            {
                "rules": [
                    {
                        "forall": [{"name": "p", "sort": "Person"}],
                        "implies": {"antecedent": "is_human(p)", "consequent": "is_mortal(p)"},
                    }
                ]
            },
        )
        assert "forall" in result
        assert "(p Person)" in result
        assert "=>" in result
        assert "rule_0" in ctx.rules

    def test_forall_constraint_rule(self):
        ctx = ConversionContext()
        stage = RulesStage()
        result = stage.process(
            ctx, {"rules": [{"forall": [{"name": "x", "sort": "IntSort"}], "constraint": "x >= 0"}]}
        )
        assert "forall" in result
        assert "(>= x 0)" in result


class TestVerificationsStage:
    """Tests for VerificationsStage."""

    def test_empty_verifications(self):
        ctx = ConversionContext()
        stage = VerificationsStage()
        result = stage.process(ctx, {"verifications": []})
        assert result == ""

    def test_simple_constraint(self):
        ctx = ConversionContext()
        stage = VerificationsStage()
        result = stage.process(
            ctx, {"verifications": [{"name": "check_positive", "constraint": "x > 0"}]}
        )
        assert "(push 1)" in result
        assert "(assert (> x 0))" in result
        assert "(check-sat)" in result
        assert "(get-model)" in result
        assert "(pop 1)" in result
        assert "query_0" in ctx.queries

    def test_existential_verification(self):
        ctx = ConversionContext()
        stage = VerificationsStage()
        result = stage.process(
            ctx,
            {
                "verifications": [
                    {
                        "name": "find_positive",
                        "exists": [{"name": "x", "sort": "IntSort"}],
                        "constraint": "x > 0",
                    }
                ]
            },
        )
        assert "exists" in result
        assert "(x Int)" in result

    def test_forall_verification(self):
        ctx = ConversionContext()
        stage = VerificationsStage()
        result = stage.process(
            ctx,
            {
                "verifications": [
                    {
                        "name": "all_positive",
                        "forall": [{"name": "x", "sort": "IntSort"}],
                        "implies": {"antecedent": "x > 0", "consequent": "x >= 1"},
                    }
                ]
            },
        )
        assert "forall" in result
        assert "=>" in result


class TestPipeline:
    """Tests for Pipeline class."""

    def test_run_empty_config(self):
        pipeline = Pipeline()
        result = pipeline.run({})
        assert "(set-logic ALL)" in result

    def test_run_full_config(self):
        pipeline = Pipeline()
        config = {
            "sorts": [{"name": "Person", "type": "DeclareSort"}],
            "functions": [{"name": "age", "domain": ["Person"], "range": "IntSort"}],
            "constants": {"people": {"sort": "Person", "members": ["alice"]}},
            "knowledge_base": ["age(alice) == 30"],
            "verifications": [{"name": "check_age", "constraint": "age(alice) > 20"}],
        }
        result = pipeline.run(config)

        assert "(set-logic ALL)" in result
        assert "(declare-sort Person 0)" in result
        assert "(declare-fun age (Person) Int)" in result
        assert "(declare-const alice Person)" in result
        assert "(assert (= (age alice) 30))" in result
        assert "(push 1)" in result
        assert "(check-sat)" in result

    def test_run_through_stage(self):
        pipeline = Pipeline()
        config = {
            "sorts": [{"name": "Person", "type": "DeclareSort"}],
            "functions": [{"name": "age", "domain": ["Person"], "range": "IntSort"}],
            "knowledge_base": ["age(alice) == 30"],
            "verifications": [{"name": "check", "constraint": "x > 0"}],
        }
        result = pipeline.run_through("functions", config)

        assert "(declare-sort Person 0)" in result
        assert "(declare-fun age" in result
        # Should not include KB or verifications
        assert "assert" not in result

    def test_run_stage(self):
        pipeline = Pipeline()
        config = {
            "sorts": [{"name": "Person", "type": "DeclareSort"}],
        }
        result = pipeline.run_stage("sorts", config)
        assert "(declare-sort Person 0)" in result

    def test_get_context(self):
        pipeline = Pipeline()
        config = {
            "sorts": [{"name": "Person", "type": "DeclareSort"}],
        }
        pipeline.run(config)
        ctx = pipeline.get_context()
        assert "Person" in ctx.sorts

    def test_reset(self):
        pipeline = Pipeline()
        pipeline.run({"sorts": [{"name": "Person", "type": "DeclareSort"}]})
        pipeline.reset()
        assert len(pipeline.get_context().sorts) == 0

    def test_unknown_stage_raises(self):
        pipeline = Pipeline()
        with pytest.raises(ValueError, match="Unknown stage"):
            pipeline.run_stage("nonexistent", {})
