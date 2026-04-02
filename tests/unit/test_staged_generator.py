"""Unit tests for the SMT-only staged generator guardrails."""

from __future__ import annotations

import pytest

from z3adapter.backends.smt2.generator import SimpleLLMClient, StagedGenerator
from z3adapter.backends.smt2.ir import (
    ConversionContext,
    SMTAssertion,
    SMTConstant,
    SMTFunction,
    SMTSort,
    SMTSortKind,
)
from z3adapter.backends.smt2.prompts import (
    BACKGROUND_KNOWLEDGE_COMMENT,
    format_functions_prompt,
)


def _base_context() -> ConversionContext:
    ctx = ConversionContext()
    ctx.sorts["Entity"] = SMTSort(
        name="Entity",
        kind=SMTSortKind.UNINTERPRETED,
        smt_name="Entity",
        smt_code="(declare-sort Entity 0)",
        emitted=True,
    )
    ctx.functions["is_blue"] = SMTFunction(
        name="is_blue",
        smt_name="is_blue",
        domain=["Entity"],
        range_sort="Bool",
        smt_code="(declare-fun is_blue (Entity) Bool)",
        emitted=True,
    )
    ctx.constants["dave"] = SMTConstant(
        name="dave",
        smt_name="dave",
        sort="Entity",
        smt_code="(declare-const dave Entity)",
        emitted=True,
    )
    ctx.kb_assertions["kb_0"] = SMTAssertion(
        id="kb_0",
        dsl_expr="",
        smt_expr="(assert (is_blue dave))",
        smt_code="(assert (is_blue dave))",
        emitted=True,
    )
    return ctx


def test_prompt_includes_full_world_model_smt() -> None:
    ctx = _base_context()

    prompt = format_functions_prompt("Dave is blue.", ctx)

    assert "Current world model SMT-LIB" in prompt
    assert "(set-logic ALL)" in prompt
    assert "(declare-sort Entity 0)" in prompt
    assert "(declare-const dave Entity)" in prompt


def test_prompt_includes_background_knowledge_rule_when_enabled() -> None:
    ctx = _base_context()

    prompt = format_functions_prompt(
        "Whales are mammals.",
        ctx,
        allow_background_knowledge=True,
    )

    assert BACKGROUND_KNOWLEDGE_COMMENT in prompt
    assert "lower-rigor" in prompt


def test_prepare_stage_output_normalizes_zero_arity_constant_forms() -> None:
    generator = StagedGenerator(SimpleLLMClient(lambda _prompt: ""))
    ctx = _base_context()

    normalized_constants = generator._prepare_stage_output(  # noqa: SLF001
        "constants",
        "(declare-fun max Entity)",
        ctx,
    )
    ctx.constants["max"] = SMTConstant(
        name="max",
        smt_name="max",
        sort="Entity",
        smt_code=normalized_constants,
        emitted=True,
    )
    normalized_assertion = generator._prepare_stage_output(  # noqa: SLF001
        "knowledge_base",
        "(assert (is_blue (max)))",
        ctx,
    )

    assert normalized_constants == "(declare-const max Entity)"
    assert normalized_assertion == "(assert (is_blue max))"


def test_prepare_stage_output_strips_stage_spillover_and_accepts_builtins() -> None:
    generator = StagedGenerator(SimpleLLMClient(lambda _prompt: ""))
    ctx = _base_context()

    normalized = generator._prepare_stage_output(  # noqa: SLF001
        "functions",
        "\n".join(
            [
                "(set-logic ALL)",
                "(declare-fun label (Entity) String)",
                "(declare-fun max Entity)",
                "(check-sat)",
            ]
        ),
        ctx,
    )

    assert "(set-logic ALL)" not in normalized
    assert "(check-sat)" not in normalized
    assert "(declare-fun label (Entity) String)" in normalized
    assert "(declare-const max Entity)" in normalized


def test_stage_local_repair_uses_world_model_context() -> None:
    prompts: list[str] = []

    def generate(prompt: str) -> str:
        prompts.append(prompt)
        if "Repair Required" in prompt and "`functions` stage" in prompt:
            return "(declare-fun is_blue (Entity) Bool)"
        if "Current Task: Define Sorts" in prompt:
            return "(declare-sort Entity 0)"
        if "Current Task: Define Functions" in prompt:
            return "(assert true)"
        if "Current Task: Declare Constants" in prompt:
            return "(declare-const dave Entity)"
        if "Current Task: Encode Knowledge Base" in prompt:
            return "(assert (is_blue dave))"
        if "Current Task: Encode the Specific Scenario" in prompt:
            return ""
        if "Current Task: Formulate the Verification Claim" in prompt:
            return "(is_blue dave)"
        raise AssertionError(f"Unexpected prompt:\n{prompt}")

    generator = StagedGenerator(SimpleLLMClient(generate), max_stage_repairs=1)
    result = generator.generate(
        text="All stated facts are grounded in the world model.",
        question="Is Dave blue?",
    )

    repair_prompts = [prompt for prompt in prompts if "Repair Required" in prompt]
    assert result.success is True
    assert len(repair_prompts) == 1
    assert "(declare-sort Entity 0)" in repair_prompts[0]
    assert "Repair ONLY the `functions` stage output." in repair_prompts[0]
    assert generator.ctx.functions["is_blue"].domain == ["Entity"]
    assert generator.ctx.constants["dave"].sort == "Entity"


def test_query_stage_rejects_solver_commands() -> None:
    generator = StagedGenerator(SimpleLLMClient(lambda _prompt: ""))

    with pytest.raises(ValueError, match="check-sat"):
        generator._prepare_stage_output(  # noqa: SLF001
            "query",
            "(assert true)\n(check-sat)",
            ConversionContext(),
        )


def test_parse_kb_hoists_declarations_and_adds_identity_equality() -> None:
    generator = StagedGenerator(SimpleLLMClient(lambda _prompt: ""))
    ctx = ConversionContext()

    generator._parse_kb(  # noqa: SLF001
        "\n".join(
            [
                "(declare-sort Entity 0)",
                "(declare-fun is_same_entity (Entity Entity) Bool)",
                "(declare-fun located_in (Entity) Entity)",
                "(declare-const a Entity)",
                "(declare-const b Entity)",
                "(declare-const portland Entity)",
                "(assert (is_same_entity a b))",
                "(assert (= (located_in b) portland))",
            ]
        ),
        ctx,
    )

    assert "is_same_entity" in ctx.functions
    assert "located_in" in ctx.functions
    assert "a" in ctx.constants
    assert "b" in ctx.constants
    assertion_codes = {assertion.smt_code for assertion in ctx.kb_assertions.values()}
    assert "(assert (is_same_entity a b))" in assertion_codes
    assert "(assert (= a b))" in assertion_codes


def test_parse_kb_preserves_background_knowledge_tags() -> None:
    generator = StagedGenerator(SimpleLLMClient(lambda _prompt: ""))
    ctx = ConversionContext()

    generator._parse_kb(  # noqa: SLF001
        "\n".join(
            [
                "(declare-sort Entity 0)",
                "(declare-fun is_mammal (Entity) Bool)",
                "(declare-const dumbo Entity)",
                "; background_knowledge",
                "(assert (is_mammal dumbo))",
            ]
        ),
        ctx,
    )

    assertion = next(iter(ctx.kb_assertions.values()))

    assert assertion.background_knowledge is True
    assert assertion.smt_code.startswith(f"{BACKGROUND_KNOWLEDGE_COMMENT}\n")
    assert assertion.smt_expr == "(assert (is_mammal dumbo))"


def test_background_knowledge_mode_requires_tags_for_assertions() -> None:
    generator = StagedGenerator(
        SimpleLLMClient(lambda _prompt: ""),
        allow_background_knowledge=True,
        require_background_knowledge_tags=True,
    )
    ctx = ConversionContext()
    ctx.sorts["Entity"] = SMTSort(
        name="Entity",
        kind=SMTSortKind.UNINTERPRETED,
        smt_name="Entity",
        smt_code="(declare-sort Entity 0)",
        emitted=True,
    )
    ctx.functions["is_mammal"] = SMTFunction(
        name="is_mammal",
        smt_name="is_mammal",
        domain=["Entity"],
        range_sort="Bool",
        smt_code="(declare-fun is_mammal (Entity) Bool)",
        emitted=True,
    )
    ctx.constants["dumbo"] = SMTConstant(
        name="dumbo",
        smt_name="dumbo",
        sort="Entity",
        smt_code="(declare-const dumbo Entity)",
        emitted=True,
    )

    with pytest.raises(ValueError, match="background_knowledge"):
        generator._prepare_stage_output(  # noqa: SLF001
            "knowledge_base",
            "(assert (is_mammal dumbo))",
            ctx,
        )


def test_stage_local_repair_can_add_background_knowledge_tags() -> None:
    prompts: list[str] = []

    def generate(prompt: str) -> str:
        prompts.append(prompt)
        if "Repair Required" in prompt and "`knowledge_base` stage" in prompt:
            return "\n".join(
                [
                    "; background_knowledge",
                    "(assert (is_mammal dumbo))",
                ]
            )
        if "Current Task: Define Sorts" in prompt:
            return "(declare-sort Entity 0)"
        if "Current Task: Define Functions" in prompt:
            return "(declare-fun is_mammal (Entity) Bool)"
        if "Current Task: Declare Constants" in prompt:
            return "(declare-const dumbo Entity)"
        if "Current Task: Encode Knowledge Base" in prompt:
            return "(assert (is_mammal dumbo))"
        if "Current Task: Encode the Specific Scenario" in prompt:
            return ""
        if "Current Task: Formulate the Verification Claim" in prompt:
            return "(is_mammal dumbo)"
        raise AssertionError(f"Unexpected prompt:\n{prompt}")

    generator = StagedGenerator(
        SimpleLLMClient(generate),
        allow_background_knowledge=True,
        require_background_knowledge_tags=True,
        max_stage_repairs=1,
    )

    result = generator.generate(
        text="Verification question context only.",
        question="Are elephants mammals?",
    )

    repair_prompts = [prompt for prompt in prompts if "Repair Required" in prompt]
    assert result.success is True
    assert len(repair_prompts) == 1
    assert "every assertion in this stage must be preceded" in repair_prompts[0]
    assertion = next(iter(generator.ctx.kb_assertions.values()))
    assert assertion.background_knowledge is True
