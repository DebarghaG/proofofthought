"""Unit tests for runtime compatibility and production-facing contracts."""

from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import pytest

import proofofthought
from z3adapter._z3 import resolve_z3_path
from z3adapter.backends.abstract import VerificationResult
from z3adapter.postprocessors.abstract import Postprocessor
from z3adapter.reasoning import (
    ArtifactExecution,
    EvaluationPipeline,
    ProofOfThought,
    QueryResult,
    StagedArtifact,
)


class _NoopClient:
    """Minimal client stub for constructor-only tests."""


class _PromptMappedClient:
    """Small Azure-style client stub for staged prompt tests."""

    def __init__(self, generate_fn):
        self._generate_fn = generate_fn
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, *, model, messages, max_completion_tokens):
        del model, max_completion_tokens
        prompt = messages[-1]["content"]
        content = self._generate_fn(prompt)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class _MetadataDroppingPostprocessor(Postprocessor):
    """Return an improved answer while omitting staged metadata fields."""

    def process(
        self,
        question: str,
        initial_result: QueryResult,
        generator,
        backend,
        llm_client,
        **kwargs,
    ) -> QueryResult:
        del question, initial_result, generator, backend, llm_client, kwargs
        return QueryResult(
            question="ignored by merge",
            answer=False,
            sat_count=0,
            unsat_count=1,
            output="unsat",
            success=True,
            num_attempts=0,
            backend="smt2",
            program_format="smt2",
            smt2_program="(check-sat)",
        )


def _success_result(artifact: StagedArtifact) -> QueryResult:
    return QueryResult(
        question=artifact.question,
        answer=True,
        sat_count=1,
        unsat_count=0,
        output="sat",
        success=True,
        num_attempts=1,
        backend="staged_smt2",
        program_format="smt2",
        smt2_program="(check-sat)",
        artifact=artifact,
        artifact_kind=artifact.artifact_kind,
        source_kind=artifact.source_kind,
    )


def test_resolve_z3_path_falls_back_to_python_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("z3adapter._z3.shutil.which", lambda *_args, **_kwargs: None)
    resolved = resolve_z3_path()
    assert resolved.endswith("venv/bin/z3")


def test_json_backend_is_removed() -> None:
    with pytest.raises(ValueError, match="removed in 2.0.0"):
        ProofOfThought(llm_client=_NoopClient(), backend="json")


def test_default_backend_is_staged() -> None:
    pot = ProofOfThought(llm_client=_NoopClient())
    assert pot.backend_type == "staged_smt2"
    assert pot.requested_backend == "staged_smt2"


def test_canonical_package_exports_match_compatibility_package() -> None:
    assert proofofthought.ProofOfThought is ProofOfThought
    assert proofofthought.StagedArtifact is StagedArtifact


def test_query_result_program_property_prefers_smt2_program() -> None:
    result = QueryResult(
        question="Can fish breathe underwater?",
        answer=True,
        sat_count=1,
        unsat_count=0,
        output="sat",
        success=True,
        num_attempts=1,
        backend="smt2",
        program_format="smt2",
        smt2_program="(check-sat)",
        program_path=str(Path("output/example.smt2")),
    )

    assert result.program == "(check-sat)"
    assert result.program_path == "output/example.smt2"


def test_staged_artifact_round_trip(tmp_path: Path) -> None:
    artifact = StagedArtifact(
        source_text="All humans are mortal.",
        question="Is Socrates mortal?",
        scenario_text="Assume Socrates is a human.",
        artifact_kind="check",
        source_kind="policy",
        annotations={"source": "demo"},
        stage_outputs={"sorts": "(declare-sort Human 0)"},
        context={"logic": "ALL"},
        context_summary="; Logic: ALL",
        foundation_smt2="(set-logic ALL)",
        program_smt2="(set-logic ALL)\n(check-sat)",
    )

    path = tmp_path / "artifact.json"
    artifact.save(path)
    reloaded = StagedArtifact.load(path)

    assert reloaded.question == artifact.question
    assert reloaded.scenario_text == artifact.scenario_text
    assert reloaded.artifact_kind == artifact.artifact_kind
    assert reloaded.source_kind == artifact.source_kind
    assert reloaded.annotations == artifact.annotations
    assert reloaded.program_smt2 == artifact.program_smt2
    assert reloaded.artifact_path == str(path)


def test_staged_artifact_save_persists_destination_path(tmp_path: Path) -> None:
    artifact = StagedArtifact(source_text="All humans are mortal.")
    path = tmp_path / "artifact.json"

    artifact.save(path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["artifact_path"] == str(path)


def test_build_foundation_formats_code_annotations() -> None:
    pot = ProofOfThought(llm_client=_NoopClient())
    artifact = pot.create_artifact(
        text="def transfer(balance: int, amount: int) -> int: ...",
        annotations={
            "preconditions": ["amount >= 0", "amount <= balance"],
            "postconditions": ["result == balance - amount"],
            "invariants": ["balance >= 0"],
        },
        artifact_kind="foundation",
        source_kind="code",
    )

    foundation_input = pot._build_foundation_input(artifact)

    assert "def transfer" in foundation_input
    assert "preconditions" in foundation_input
    assert "postconditions" in foundation_input
    assert artifact.source_kind == "code"
    assert artifact.artifact_kind == "foundation"


def test_query_splits_legacy_one_shot_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pot = ProofOfThought(llm_client=_NoopClient())
    captured: dict[str, str] = {}

    def _fake_run_through_stage(
        artifact: StagedArtifact,
        stage_name: str,
        *,
        from_stage: str = "sorts",
        max_tokens: int = 4096,
        artifact_path: str | Path | None = None,
    ) -> StagedArtifact:
        del stage_name, from_stage, max_tokens, artifact_path
        captured["source_text"] = artifact.source_text
        captured["question"] = artifact.question
        artifact.program_smt2 = "(check-sat)"
        return artifact

    def _fake_execute_artifact(
        artifact: StagedArtifact,
        *,
        save_program: bool = False,
        program_path: str | None = None,
        save_artifact: bool = False,
        artifact_path: str | Path | None = None,
        enable_postprocessing: bool = True,
    ) -> QueryResult:
        del save_program, program_path, save_artifact, artifact_path, enable_postprocessing
        return _success_result(artifact)

    monkeypatch.setattr(pot, "run_through_stage", _fake_run_through_stage)
    monkeypatch.setattr(pot, "execute_artifact", _fake_execute_artifact)

    pot.query(
        "Dave is smart. Red things are blue.\n\nQuestion: Harry is blue.",
    )

    assert captured["source_text"] == "Dave is smart. Red things are blue."
    assert captured["question"] == "Harry is blue."


def test_evaluation_pipeline_passes_text_field(tmp_path: Path) -> None:
    pot = ProofOfThought(llm_client=_NoopClient())
    captured: dict[str, str | None] = {}

    def _fake_query(
        *,
        question: str,
        text: str | None = None,
        save_program: bool = False,
        program_path: str | None = None,
        **kwargs,
    ) -> QueryResult:
        del save_program, program_path, kwargs
        captured["question"] = question
        captured["text"] = text
        return QueryResult(
            question=question,
            answer=True,
            sat_count=1,
            unsat_count=0,
            output="sat",
            success=True,
            num_attempts=1,
            backend="staged_smt2",
            program_format="smt2",
            smt2_program="(check-sat)",
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(pot, "query", _fake_query)

    try:
        evaluator = EvaluationPipeline(proof_of_thought=pot, output_dir=str(tmp_path), num_workers=1)
        evaluator.evaluate(
            dataset=[
                {
                    "id": "sample-1",
                    "context": "All humans are mortal.",
                    "claim": "Socrates is mortal.",
                    "answer": True,
                }
            ],
            text_field="context",
            question_field="claim",
            answer_field="answer",
            id_field="id",
            max_samples=1,
            skip_existing=False,
        )
    finally:
        monkeypatch.undo()

    assert captured["text"] == "All humans are mortal."
    assert captured["question"] == "Socrates is mortal."


def test_run_check_promotes_trace_backed_artifact_to_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pot = ProofOfThought(llm_client=_NoopClient())
    foundation = pot.create_artifact(
        text="Tool calls must respect account balance invariants.",
        artifact_kind="foundation",
        source_kind="policy",
    )

    def _fake_run_stage(
        artifact: StagedArtifact,
        stage_name: str,
        *,
        rerun_downstream: bool = True,
        max_tokens: int = 4096,
        artifact_path: str | Path | None = None,
    ) -> StagedArtifact:
        del stage_name, rerun_downstream, max_tokens, artifact_path
        artifact.program_smt2 = "(check-sat)"
        return artifact

    def _fake_execute_artifact(
        artifact: StagedArtifact,
        *,
        save_program: bool = False,
        program_path: str | None = None,
        save_artifact: bool = False,
        artifact_path: str | Path | None = None,
        enable_postprocessing: bool = True,
    ) -> QueryResult:
        del save_program, program_path, save_artifact, artifact_path, enable_postprocessing
        return _success_result(artifact)

    monkeypatch.setattr(pot, "run_stage", _fake_run_stage)
    monkeypatch.setattr(pot, "execute_artifact", _fake_execute_artifact)

    result = pot.run_check(
        foundation,
        question="Would the proposed withdrawal violate the account invariant?",
        scenario_text="Agent proposes withdrawing 50 credits from an account with balance 20.",
        check_name="withdrawal_guardrail",
        trace_entries=[
            {"entry_type": "action", "content": "withdraw(account_id='acct_1', amount=50)"},
            {"entry_type": "observation", "content": "current_balance=20"},
        ],
    )

    assert foundation.artifact_kind == "foundation"
    assert foundation.question == ""
    assert foundation.scenario_text == ""
    assert foundation.trace_entries == []
    assert foundation.check_history == []
    assert result.artifact is not foundation
    assert result.artifact is not None
    assert result.artifact.artifact_kind == "audit"
    assert len(result.artifact.trace_entries) == 2
    assert result.artifact.check_history[-1].name == "withdrawal_guardrail"
    assert result.check_name == "withdrawal_guardrail"
    assert result.artifact_kind == "audit"


def test_fork_artifact_preserves_foundation_and_clears_check_state() -> None:
    pot = ProofOfThought(llm_client=_NoopClient())
    artifact = StagedArtifact(
        source_text="All account transfers require approval.",
        question="Can the agent transfer 100 credits?",
        scenario_text="The agent has no approval token.",
        artifact_kind="check",
        source_kind="policy",
        stage_outputs={
            "sorts": "(declare-sort Transfer 0)",
            "functions": "(declare-fun approved (Transfer) Bool)",
            "constants": "(declare-const transfer_0 Transfer)",
            "knowledge_base": "(assert (=> true (approved transfer_0)))",
            "scenario": "(assert true)",
            "query": "(check-sat)",
        },
        foundation_smt2="(set-logic ALL)",
        program_smt2="(set-logic ALL)\n(check-sat)",
    )

    forked = pot.fork_artifact(
        artifact,
        artifact_kind="check",
        question="Can the agent retry with approval?",
        scenario_text="The agent now has a valid approval token.",
    )

    assert forked.question == "Can the agent retry with approval?"
    assert forked.scenario_text == "The agent now has a valid approval token."
    assert forked.stage_outputs["knowledge_base"] == artifact.stage_outputs["knowledge_base"]
    assert "scenario" not in forked.stage_outputs
    assert "query" not in forked.stage_outputs


def test_run_check_save_artifact_persists_recorded_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pot = ProofOfThought(llm_client=_NoopClient())
    foundation = pot.create_artifact(
        text="Transfers above 10000 require approval.",
        artifact_kind="foundation",
        source_kind="policy",
    )

    def _fake_run_stage(
        artifact: StagedArtifact,
        stage_name: str,
        *,
        rerun_downstream: bool = True,
        max_tokens: int = 4096,
        artifact_path: str | Path | None = None,
    ) -> StagedArtifact:
        del stage_name, rerun_downstream, max_tokens, artifact_path
        artifact.program_smt2 = "(check-sat)"
        return artifact

    def _fake_execute_artifact(
        artifact: StagedArtifact,
        *,
        save_program: bool = False,
        program_path: str | None = None,
        save_artifact: bool = False,
        artifact_path: str | Path | None = None,
        enable_postprocessing: bool = True,
    ) -> QueryResult:
        del save_program, program_path, save_artifact, artifact_path, enable_postprocessing
        return _success_result(artifact)

    monkeypatch.setattr(pot, "run_stage", _fake_run_stage)
    monkeypatch.setattr(pot, "execute_artifact", _fake_execute_artifact)

    saved_path = tmp_path / "guardrail.artifact.json"
    result = pot.run_check(
        foundation,
        question="May the agent submit the transfer?",
        scenario_text="The transfer amount is 25000 and there is one approval.",
        check_name="transfer_guardrail",
        save_artifact=True,
        artifact_path=saved_path,
    )

    reloaded = StagedArtifact.load(saved_path)

    assert foundation.check_history == []
    assert result.artifact is not None
    assert result.artifact.artifact_path == str(saved_path)
    assert reloaded.latest_check is not None
    assert reloaded.latest_check.name == "transfer_guardrail"
    assert reloaded.latest_check.question == "May the agent submit the transfer?"


def test_query_save_artifact_persists_recorded_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pot = ProofOfThought(llm_client=_NoopClient())

    def _fake_run_through_stage(
        artifact: StagedArtifact,
        stage_name: str,
        *,
        from_stage: str = "sorts",
        max_tokens: int = 4096,
        artifact_path: str | Path | None = None,
    ) -> StagedArtifact:
        del stage_name, from_stage, max_tokens, artifact_path
        artifact.program_smt2 = "(check-sat)"
        return artifact

    def _fake_execute_artifact(
        artifact: StagedArtifact,
        *,
        save_program: bool = False,
        program_path: str | None = None,
        save_artifact: bool = False,
        artifact_path: str | Path | None = None,
        enable_postprocessing: bool = True,
    ) -> QueryResult:
        del save_program, program_path, save_artifact, artifact_path, enable_postprocessing
        return _success_result(artifact)

    monkeypatch.setattr(pot, "run_through_stage", _fake_run_through_stage)
    monkeypatch.setattr(pot, "execute_artifact", _fake_execute_artifact)

    saved_path = tmp_path / "query.artifact.json"
    result = pot.query(
        "Is Socrates mortal?",
        text="All humans are mortal. Socrates is a human.",
        save_artifact=True,
        artifact_path=saved_path,
    )

    reloaded = StagedArtifact.load(saved_path)

    assert result.artifact is not None
    assert result.artifact.artifact_path == str(saved_path)
    assert reloaded.latest_check is not None
    assert reloaded.latest_check.question == "Is Socrates mortal?"
    assert reloaded.latest_check.success is True


def test_query_failure_save_artifact_persists_recorded_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pot = ProofOfThought(llm_client=_NoopClient(), max_attempts=1)

    def _fake_run_through_stage(
        artifact: StagedArtifact,
        stage_name: str,
        *,
        from_stage: str = "sorts",
        max_tokens: int = 4096,
        artifact_path: str | Path | None = None,
    ) -> StagedArtifact:
        del stage_name, from_stage, max_tokens, artifact_path
        artifact.program_smt2 = "(check-sat)"
        return artifact

    def _fake_execute_artifact(
        artifact: StagedArtifact,
        *,
        save_program: bool = False,
        program_path: str | None = None,
        save_artifact: bool = False,
        artifact_path: str | Path | None = None,
        enable_postprocessing: bool = True,
    ) -> QueryResult:
        del save_program, program_path, save_artifact, artifact_path, enable_postprocessing
        artifact.execution = ArtifactExecution(
            success=False,
            answer=None,
            sat_count=1,
            unsat_count=1,
            output="sat\nunsat",
            error="Ambiguous verification result",
            failure_code="ambiguous_verification_result",
        )
        return QueryResult(
            question=artifact.question,
            answer=None,
            sat_count=1,
            unsat_count=1,
            output="sat\nunsat",
            success=False,
            num_attempts=1,
            backend="staged_smt2",
            program_format="smt2",
            smt2_program="(check-sat)",
            error="Ambiguous verification result",
            failure_code="ambiguous_verification_result",
            artifact=artifact,
            artifact_kind=artifact.artifact_kind,
            source_kind=artifact.source_kind,
        )

    monkeypatch.setattr(pot, "run_through_stage", _fake_run_through_stage)
    monkeypatch.setattr(pot, "execute_artifact", _fake_execute_artifact)

    saved_path = tmp_path / "query-failure.artifact.json"
    result = pot.query(
        "Is the result definitive?",
        text="All relevant facts are already listed.",
        save_artifact=True,
        artifact_path=saved_path,
    )

    reloaded = StagedArtifact.load(saved_path)

    assert result.success is False
    assert reloaded.latest_check is not None
    assert reloaded.latest_check.failure_code == "ambiguous_verification_result"
    assert reloaded.execution.failure_code == "ambiguous_verification_result"
    assert reloaded.execution.output == "sat\nunsat"


def test_query_rejects_ungrounded_question_early(tmp_path: Path) -> None:
    pot = ProofOfThought(llm_client=_NoopClient())

    saved_path = tmp_path / "ungrounded.artifact.json"
    result = pot.query(
        "Is Socrates mortal?",
        save_artifact=True,
        artifact_path=saved_path,
    )

    reloaded = StagedArtifact.load(saved_path)

    assert result.success is False
    assert result.failure_code == "unsupported_without_grounding"
    assert reloaded.latest_check is not None
    assert reloaded.latest_check.failure_code == "unsupported_without_grounding"


def test_query_allows_explicit_background_knowledge_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _generate(prompt: str) -> str:
        if "Current Task: Define Sorts" in prompt:
            assert "Verification question context for selecting relevant background knowledge" in prompt
            return "(declare-sort Entity 0)"
        if "Current Task: Define Functions" in prompt:
            return "\n".join(
                [
                    "(declare-fun is_elephant (Entity) Bool)",
                    "(declare-fun is_mammal (Entity) Bool)",
                ]
            )
        if "Current Task: Declare Constants" in prompt:
            return "(declare-const dumbo Entity)"
        if "Current Task: Encode Knowledge Base" in prompt:
            return "\n".join(
                [
                    "; background_knowledge",
                    "(assert (is_elephant dumbo))",
                    "; background_knowledge",
                    "(assert (forall ((x Entity)) (=> (is_elephant x) (is_mammal x))))",
                ]
            )
        if "Current Task: Encode the Specific Scenario" in prompt:
            return ""
        if "Current Task: Formulate the Verification Claim" in prompt:
            return "(is_mammal dumbo)"
        raise AssertionError(f"Unexpected prompt:\n{prompt}")

    pot = ProofOfThought(
        llm_client=_PromptMappedClient(_generate),
        allow_background_knowledge=True,
    )

    monkeypatch.setattr(
        pot.backend,
        "execute_from_string",
        lambda _program: VerificationResult(
            success=True,
            answer=True,
            sat_count=0,
            unsat_count=1,
            output="unsat",
            failure_code=None,
        ),
    )

    result = pot.query("Are elephants mammals?")

    assert result.success is True
    assert result.background_knowledge_used is True
    assert result.rigor_level == "background_informed"
    assert result.artifact is not None
    assert result.artifact.execution.background_knowledge_used is True
    assert "; background_knowledge" in result.artifact.program_smt2


def test_query_requires_background_knowledge_tags_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _generate(prompt: str) -> str:
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

    pot = ProofOfThought(
        llm_client=_PromptMappedClient(_generate),
        allow_background_knowledge=True,
    )
    called = False

    def _fake_execute_from_string(program: str):
        nonlocal called
        called = True
        del program
        raise AssertionError("solver should not run when background knowledge is untagged")

    monkeypatch.setattr(pot.backend, "execute_from_string", _fake_execute_from_string)

    result = pot.query("Are elephants mammals?")

    assert called is False
    assert result.success is False
    assert result.failure_code == "background_knowledge_tags_missing"
    assert result.background_knowledge_used is False
    assert result.rigor_level == "strict_grounded"


def test_postprocessing_preserves_staged_metadata() -> None:
    pot = ProofOfThought(llm_client=_NoopClient())
    pot.postprocessors = [_MetadataDroppingPostprocessor()]
    artifact = StagedArtifact(
        source_text="All humans are mortal.",
        question="Is Socrates mortal?",
        artifact_kind="audit",
        source_kind="code",
    )
    initial_result = QueryResult(
        question="Is Socrates mortal?",
        answer=True,
        sat_count=1,
        unsat_count=0,
        output="sat",
        success=True,
        num_attempts=2,
        backend="staged_smt2",
        program_format="smt2",
        smt2_program="(check-sat)",
        program_path="output/example.smt2",
        artifact=artifact,
        artifact_kind="audit",
        source_kind="code",
        check_name="existing-check",
        background_knowledge_used=True,
        rigor_level="background_informed",
    )

    merged = pot._apply_postprocessors(
        question=initial_result.question,
        initial_result=initial_result,
        temperature=0.1,
        max_tokens=256,
    )

    assert merged.answer is False
    assert merged.backend == "staged_smt2"
    assert merged.artifact is artifact
    assert merged.program_path == "output/example.smt2"
    assert merged.artifact_kind == "audit"
    assert merged.source_kind == "code"
    assert merged.check_name == "existing-check"
    assert merged.background_knowledge_used is True
    assert merged.rigor_level == "background_informed"


def test_execute_artifact_repairs_solver_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pot = ProofOfThought(llm_client=_NoopClient(), max_solver_repairs=1)
    artifact = StagedArtifact(
        source_text="All humans are mortal.",
        question="Is Socrates mortal?",
        program_smt2="(broken)",
        artifact_kind="check",
        source_kind="policy",
    )
    calls: list[str] = []

    def _fake_execute_from_string(program: str):
        calls.append(program)
        if program == "(broken)":
            return VerificationResult(
                success=False,
                answer=None,
                sat_count=0,
                unsat_count=0,
                output='(error "line 1: broken")',
                error='(error "line 1: broken")',
                failure_code="solver_error",
            )
        return VerificationResult(
            success=True,
            answer=True,
            sat_count=0,
            unsat_count=1,
            output="unsat",
            failure_code=None,
        )

    def _fake_repair_program(
        artifact_arg: StagedArtifact,
        *,
        program: str,
        solver_error: str,
        max_tokens: int = 4096,
    ) -> str:
        del artifact_arg, solver_error, max_tokens
        assert program == "(broken)"
        return "(set-logic ALL)\n; Verification mode: entailment\n(check-sat)"

    monkeypatch.setattr(pot.backend, "execute_from_string", _fake_execute_from_string)
    monkeypatch.setattr(pot, "_repair_smt2_program", _fake_repair_program)

    result = pot.execute_artifact(artifact)

    assert calls == ["(broken)", "(set-logic ALL)\n; Verification mode: entailment\n(check-sat)"]
    assert result.success is True
    assert result.answer is True
    assert artifact.program_smt2 == "(set-logic ALL)\n; Verification mode: entailment\n(check-sat)"


def test_create_artifact_preserves_empty_source_text_for_question_only() -> None:
    pot = ProofOfThought(llm_client=_NoopClient())

    artifact = pot.create_artifact(question="Is Socrates mortal?")

    assert artifact.source_text == ""
    assert artifact.question == "Is Socrates mortal?"


def test_execute_artifact_rejects_ungrounded_question_without_calling_solver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pot = ProofOfThought(llm_client=_NoopClient())
    artifact = StagedArtifact(
        source_text="",
        question="Is Socrates mortal?",
        program_smt2="(set-logic ALL)\n(check-sat)",
    )
    called = False

    def _fake_execute_from_string(program: str):
        nonlocal called
        called = True
        del program
        raise AssertionError("solver should not be called for ungrounded questions")

    monkeypatch.setattr(pot.backend, "execute_from_string", _fake_execute_from_string)

    result = pot.execute_artifact(artifact)

    assert called is False
    assert result.success is False
    assert result.failure_code == "unsupported_without_grounding"
    assert artifact.execution.failure_code == "unsupported_without_grounding"


def test_execute_artifact_rejects_vacuous_world_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pot = ProofOfThought(llm_client=_NoopClient())
    artifact = StagedArtifact(
        source_text="All facts are known.",
        question="Is anything true?",
        program_smt2="(set-logic ALL)\n(assert true)\n(check-sat)",
        context={
            "kb_assertions": {
                "kb_0": {
                    "smt_code": "(assert true)",
                }
            }
        },
    )
    called = False

    def _fake_execute_from_string(program: str):
        nonlocal called
        called = True
        del program
        raise AssertionError("solver should not be called for vacuous world models")

    monkeypatch.setattr(pot.backend, "execute_from_string", _fake_execute_from_string)

    result = pot.execute_artifact(artifact)

    assert called is False
    assert result.success is False
    assert result.failure_code == "vacuous_world_model"
    assert artifact.execution.failure_code == "vacuous_world_model"
