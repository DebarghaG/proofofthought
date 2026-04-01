"""Integration tests for document-grounded staged verification."""

from __future__ import annotations

import json
import shutil

import pytest

from z3adapter.backends.smt2 import SimpleLLMClient, StagedGenerator
from z3adapter.reasoning import (
    DocumentVerificationPipeline,
    OptionVerificationResult,
    ProofOfThought,
    QuestionVerificationResult,
)


def z3_available() -> bool:
    return shutil.which("z3") is not None


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeChatCompletions:
    def __init__(self, client: FakeLLMClient) -> None:
        self.client = client

    def create(
        self,
        model: str,
        messages: list[dict],
        max_completion_tokens: int,
        response_format: dict | None = None,
    ) -> _FakeResponse:
        del model, max_completion_tokens, response_format
        prompt = messages[-1]["content"]
        return _FakeResponse(self.client.generate(prompt))


class _FakeChat:
    def __init__(self, client: FakeLLMClient) -> None:
        self.completions = _FakeChatCompletions(client)


class FakeLLMClient:
    def __init__(self) -> None:
        self.chat = _FakeChat(self)

    def generate(self, prompt: str) -> str:
        if "TASK: QUESTION_SCENARIO" in prompt:
            return "NONE"

        if "TASK: OPTION_CLAIM" in prompt:
            answer = self._extract_tag(prompt, "answer_option").lower()
            if "alice has priority support" in answer:
                return json.dumps({"kind": "claim", "proposition": "(has_priority_support alice)"})
            if "alice does not have priority support" in answer:
                return json.dumps(
                    {"kind": "claim", "proposition": "(not (has_priority_support alice))"}
                )
            if "does not determine whether bob has priority support" in answer:
                return json.dumps(
                    {"kind": "underdetermined", "proposition": "(has_priority_support bob)"}
                )
            return json.dumps({"kind": "unknown", "proposition": None})

        if "Current Task: Define Sorts" in prompt:
            if "Alice is a premium subscriber." in prompt:
                return ""
            return "(declare-sort User 0)"

        if "Current Task: Define Functions" in prompt:
            if "Alice is a premium subscriber." in prompt:
                return ""
            return "\n".join(
                [
                    "(declare-fun premium_subscriber (User) Bool)",
                    "(declare-fun has_priority_support (User) Bool)",
                ]
            )

        if "Current Task: Declare Constants" in prompt:
            if "Alice is a premium subscriber." in prompt:
                return "\n".join(
                    [
                        "(declare-const alice User)",
                        "(declare-const bob User)",
                    ]
                )
            return ""

        if "Current Task: Encode Knowledge Base" in prompt:
            if "Alice is a premium subscriber." in prompt:
                return "(assert (premium_subscriber alice))"
            return (
                "(assert (forall ((x User)) "
                "(=> (premium_subscriber x) (has_priority_support x))))"
            )

        raise AssertionError(f"Unexpected prompt:\n{prompt}")

    def _extract_tag(self, prompt: str, tag: str) -> str:
        start_tag = f"<{tag}>"
        end_tag = f"</{tag}>"
        start = prompt.index(start_tag) + len(start_tag)
        end = prompt.index(end_tag)
        return prompt[start:end].strip()


@pytest.fixture
def qa_output_record() -> dict:
    return {
        "metadata": {
            "company": "acme",
            "industry": "tech",
            "doc_type": "terms-of-service",
            "source_url": "https://example.com/policy",
        },
        "chunks": [
            {
                "chunk": {
                    "chunk_index": 0,
                    "sentence_start": 0,
                    "sentence_end": 2,
                    "num_sentences": 2,
                    "text": (
                        "All premium subscribers have priority support. "
                        "Premium subscribers are users."
                    ),
                },
                "qa_pairs": [
                    {
                        "question": "Does Alice have priority support?",
                        "question_type": "interpretation",
                        "difficulty": "easy",
                        "tags": ["priority-support"],
                        "answers": {
                            "valid": "Yes, Alice has priority support.",
                            "invalid": "No, Alice does not have priority support.",
                            "ambiguous": None,
                        },
                    }
                ],
            },
            {
                "chunk": {
                    "chunk_index": 1,
                    "sentence_start": 2,
                    "sentence_end": 4,
                    "num_sentences": 2,
                    "text": "Alice is a premium subscriber. Bob is a user.",
                },
                "qa_pairs": [
                    {
                        "question": "Does Bob have priority support?",
                        "question_type": "edge_case",
                        "difficulty": "medium",
                        "tags": ["priority-support", "ambiguity"],
                        "answers": {
                            "valid": None,
                            "invalid": None,
                            "ambiguous": (
                                "The document does not determine whether Bob has priority support."
                            ),
                        },
                    }
                ],
            },
        ],
    }


@pytest.fixture
def staged_pot() -> ProofOfThought:
    return ProofOfThought(
        llm_client=FakeLLMClient(),
        model="fake-model",
        backend="staged_smt2",
    )


@pytest.mark.skipif(not z3_available(), reason="Z3 not installed")
def test_document_verification_pipeline_builds_and_scores(
    staged_pot: ProofOfThought,
    qa_output_record: dict,
    tmp_path,
) -> None:
    pipeline = DocumentVerificationPipeline(staged_pot, output_dir=tmp_path)
    result = pipeline.evaluate_dataset([qa_output_record])

    assert result.metrics.documents_processed == 1
    assert result.metrics.documents_failed == 0
    assert result.metrics.total_questions == 2
    assert result.metrics.total_options == 3
    assert result.metrics.correct_options == 3
    assert result.metrics.accuracy == 1.0
    assert result.metrics.unsound_supported_options == 0
    assert result.metrics.soundness == 1.0

    doc_result = result.documents[0]
    assert doc_result.metrics is not None
    assert doc_result.metrics.supported_options == 2
    assert doc_result.metrics.unsound_supported_options == 0
    assert doc_result.metrics.contradicted_options == 1
    assert doc_result.metrics.unresolved_options == 0
    assert doc_result.metrics.soundness == 1.0

    alice_result = doc_result.question_results[0]
    bob_result = doc_result.question_results[1]

    assert alice_result.question_status == "supported"
    assert alice_result.scenario_smt2 == ""
    assert alice_result.options[0].proposition_smt2 == "(has_priority_support alice)"
    assert alice_result.options[0].status == "supported"
    assert alice_result.options[1].status == "contradicted"

    assert bob_result.question_status == "unresolved"
    assert bob_result.options[0].proposition_smt2 == "(has_priority_support bob)"
    assert bob_result.options[0].status == "supported"

    assert (tmp_path / "document_models" / "tech__acme__terms-of-service.json").exists()
    assert (tmp_path / "document_results" / "tech__acme__terms-of-service.json").exists()
    assert (tmp_path / "document_programs" / "tech__acme__terms-of-service.smt2").exists()
    assert (tmp_path / "aggregate_metrics.json").exists()


@pytest.mark.skipif(not z3_available(), reason="Z3 not installed")
def test_document_verification_pipeline_applies_subset_selector(
    staged_pot: ProofOfThought,
    qa_output_record: dict,
    tmp_path,
) -> None:
    sample_selector = [
        {
            "company": "acme",
            "industry": "tech",
            "doc_type": "terms-of-service",
            "question": "Does Bob have priority support?",
        }
    ]
    selector_path = tmp_path / "qa_sample_subset.json"
    selector_path.write_text(json.dumps(sample_selector), encoding="utf-8")

    pipeline = DocumentVerificationPipeline(staged_pot)
    result = pipeline.evaluate_dataset(
        [qa_output_record],
        sample_filter=selector_path,
    )

    assert result.metrics.total_questions == 1
    assert result.metrics.total_options == 1
    assert result.documents[0].question_results[0].question == "Does Bob have priority support?"


def test_staged_generator_normalizes_enum_values_and_rewrites_aliases() -> None:
    def generate(prompt: str) -> str:
        if "Current Task: Define Sorts" in prompt:
            return "\n".join(
                [
                    "(declare-sort User 0)",
                    "(declare-datatypes ((State 0))",
                    "  (((State",
                    "     (PR) (NY)))))",
                ]
            )
        if "Current Task: Define Functions" in prompt:
            return "(declare-fun is_resident_of_state (User State) Bool)"
        if "Current Task: Declare Constants" in prompt:
            return "\n".join(
                [
                    "(declare-const PR State)",
                    "(declare-const user0 User)",
                ]
            )
        if "Current Task: Encode Knowledge Base" in prompt:
            return "(assert (is_resident_of_state user0 PR))"
        raise AssertionError(f"Unexpected prompt:\n{prompt}")

    generator = StagedGenerator(SimpleLLMClient(generate))
    result = generator.generate(
        text="Residents of PR and NY are listed.",
        question="",
        stages=["sorts", "functions", "constants", "knowledge_base"],
    )

    assert result.success is True

    smt2 = generator.compose_context_program(include_scenario=False, include_queries=False)
    assert "(declare-datatypes ((State 0)) (((pr) (ny))))" in smt2
    assert "(declare-const pr State)" not in smt2
    assert "(declare-const user0 User)" in smt2
    assert "(assert (is_resident_of_state user0 pr))" in smt2


def test_document_model_materializes_state_agreement_groups() -> None:
    class StateAgreementLLM(FakeLLMClient):
        def generate(self, prompt: str) -> str:
            if "Current Task: Define Sorts" in prompt:
                return "\n".join(
                    [
                        "(declare-sort Platform 0)",
                        "(declare-sort User 0)",
                        "(declare-sort Account 0)",
                        "(declare-sort Address 0)",
                        "(declare-sort UserAgreement 0)",
                        "(declare-datatypes ((UsStateOrTerritory 0)) (((PR) (NY) (CA) (TX) (FL))))",
                    ]
                )
            if "Current Task: Define Functions" in prompt:
                return "\n".join(
                    [
                        "(declare-fun state_of_residence (User) UsStateOrTerritory)",
                        "(declare-fun gemini_account (User) Account)",
                        "(declare-fun account_profile_address (Account) Address)",
                        "(declare-fun address_state (Address) UsStateOrTerritory)",
                        "(declare-fun user_agreement_for_state (Platform UsStateOrTerritory) UserAgreement)",
                        "(declare-fun governing_user_agreement (Platform User) UserAgreement)",
                    ]
                )
            if "Current Task: Declare Constants" in prompt:
                return "(declare-const gemini Platform)"
            if "Current Task: Encode Knowledge Base" in prompt:
                return "\n".join(
                    [
                        "(assert (forall ((u User)) (= (state_of_residence u) (address_state (account_profile_address (gemini_account u))))))",
                        "(assert (forall ((p Platform) (u User)) (= (governing_user_agreement p u) (user_agreement_for_state (state_of_residence u)))))",
                    ]
                )
            return super().generate(prompt)

    staged_pot = ProofOfThought(
        llm_client=StateAgreementLLM(),
        model="fake-model",
        backend="staged_smt2",
    )
    pipeline = DocumentVerificationPipeline(staged_pot)
    chunk_text = (
        "Residents of NY, TX are subject to the first agreement. "
        "Residents of CA, FL, PR are subject to the second agreement. "
        'For purposes of this landing page, "state of residence" means the state reflected '
        "in the address on your Gemini account profile."
    )

    model = pipeline.build_document_model(
        document_text=chunk_text,
        chunks=[
            {
                "chunk_index": 0,
                "text": chunk_text,
            }
        ],
        metadata={"company": "gemini", "industry": "finance", "doc_type": "terms-of-service"},
    )

    assert "(declare-const agreement_group_1 UserAgreement)" in model.foundation_smt2
    assert "(declare-const agreement_group_2 UserAgreement)" in model.foundation_smt2
    assert "(assert (distinct agreement_group_1 agreement_group_2))" in model.foundation_smt2
    assert (
        "(assert (= (user_agreement_for_state gemini ny) agreement_group_1))"
        in model.foundation_smt2
    )
    assert (
        "(assert (= (user_agreement_for_state gemini tx) agreement_group_1))"
        in model.foundation_smt2
    )
    assert (
        "(assert (= (user_agreement_for_state gemini ca) agreement_group_2))"
        in model.foundation_smt2
    )
    assert (
        "(assert (= (user_agreement_for_state gemini pr) agreement_group_2))"
        in model.foundation_smt2
    )


def test_question_scenario_renames_conflicting_symbols() -> None:
    class ScenarioCollisionLLM(FakeLLMClient):
        def generate(self, prompt: str) -> str:
            if "TASK: QUESTION_SCENARIO" in prompt:
                return "\n".join(
                    [
                        "(declare-const me User)",
                        "(assert (= me me))",
                    ]
                )
            if "Current Task: Define Sorts" in prompt:
                return "\n".join(
                    [
                        "(declare-sort User 0)",
                        "(declare-datatypes ((State 0)) (((ME))))",
                    ]
                )
            if "Current Task: Define Functions" in prompt:
                return "(declare-fun has_priority_support (User) Bool)"
            return ""

    staged_pot = ProofOfThought(
        llm_client=ScenarioCollisionLLM(),
        model="fake-model",
        backend="staged_smt2",
    )
    pipeline = DocumentVerificationPipeline(staged_pot)
    model = pipeline.build_document_model(
        document_text="Users may have support.",
        chunks=[{"chunk_index": 0, "text": "Users may have support."}],
        metadata={"company": "acme", "industry": "tech", "doc_type": "terms"},
    )

    scenario = pipeline._generate_question_scenario(
        document_model=model,
        question="Does the scenario mention me?",
        chunk_text="Users may have support.",
    )

    assert "(declare-const scenario_me User)" in scenario
    assert "(assert (= scenario_me scenario_me))" in scenario
    assert "(declare-const me User)" not in scenario


def test_document_soundness_counts_supported_false_positives(staged_pot: ProofOfThought) -> None:
    pipeline = DocumentVerificationPipeline(staged_pot)
    metrics = pipeline._calculate_document_metrics(
        [
            QuestionVerificationResult(
                question="Q1",
                chunk_index=0,
                chunk_text="",
                options=[
                    OptionVerificationResult(
                        option_type="valid",
                        question="Q1",
                        answer_text="good valid",
                        chunk_index=0,
                        claim_kind="claim",
                        proposition_smt2="true",
                        status="supported",
                        expected_status="supported",
                        is_correct=True,
                    ),
                    OptionVerificationResult(
                        option_type="invalid",
                        question="Q1",
                        answer_text="bad invalid accepted",
                        chunk_index=0,
                        claim_kind="claim",
                        proposition_smt2="true",
                        status="supported",
                        expected_status="contradicted",
                        is_correct=False,
                    ),
                    OptionVerificationResult(
                        option_type="ambiguous",
                        question="Q1",
                        answer_text="good ambiguous",
                        chunk_index=0,
                        claim_kind="underdetermined",
                        proposition_smt2="maybe",
                        status="supported",
                        expected_status="supported",
                        is_correct=True,
                    ),
                ],
            )
        ]
    )

    assert metrics.supported_options == 3
    assert metrics.unsound_supported_options == 1
    assert metrics.soundness == pytest.approx(2 / 3)
