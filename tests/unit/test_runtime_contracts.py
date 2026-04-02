"""Unit tests for runtime compatibility and production-facing contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import proofofthought
from z3adapter._z3 import resolve_z3_path
from z3adapter.postprocessors.abstract import Postprocessor
from z3adapter.reasoning import ArtifactExecution, ProofOfThought, QueryResult, StagedArtifact


class _NoopClient:
    """Minimal client stub for constructor-only tests."""


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
        save_artifact=True,
        artifact_path=saved_path,
    )

    reloaded = StagedArtifact.load(saved_path)

    assert result.success is False
    assert reloaded.latest_check is not None
    assert reloaded.latest_check.failure_code == "ambiguous_verification_result"
    assert reloaded.execution.failure_code == "ambiguous_verification_result"
    assert reloaded.execution.output == "sat\nunsat"


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
