"""ProofOfThought: staged-first API for Z3-based reasoning."""

from __future__ import annotations

import json
import logging
import os
import traceback
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from z3adapter._version import __version__
from z3adapter.backends.smt2 import STAGE_ORDER, StagedGenerator
from z3adapter.backends.smt2.backend import StagedSMT2Backend
from z3adapter.reasoning.program_generator import Z3ProgramGenerator
from z3adapter.reasoning.staged_artifact import (
    ArtifactExecution,
    ArtifactKind,
    ArtifactTraceEntry,
    SourceKind,
    StageName,
    StagedArtifact,
    TraceEntryKind,
)

if TYPE_CHECKING:
    from z3adapter.postprocessors.abstract import Postprocessor

logger = logging.getLogger(__name__)

BackendType = Literal["smt2", "staged_smt2"]
ProgramFormat = Literal["smt2"]

JSON_BACKEND_REMOVAL_MESSAGE = (
    "ProofOfThought(..., backend='json') was removed in 2.0.0. "
    "Use the staged SMT-LIB flow in this release, or refer to the legacy 1.0.1 docs."
)


class _StagedPromptClient:
    """Adapter that exposes a simple prompt -> text interface for staged generation."""

    def __init__(
        self,
        llm_client: Any,
        model: str,
        max_completion_tokens: int = 4096,
    ) -> None:
        self.llm_client = llm_client
        self.model = model
        self.max_completion_tokens = max_completion_tokens

    def generate(self, prompt: str) -> str:
        response = self.llm_client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=self.max_completion_tokens,
        )
        content = response.choices[0].message.content
        return content or ""


@dataclass
class QueryResult:
    """Result of a reasoning query."""

    question: str
    answer: bool | None
    sat_count: int
    unsat_count: int
    output: str
    success: bool
    num_attempts: int
    backend: BackendType = "staged_smt2"
    program_format: ProgramFormat | None = None
    smt2_program: str | None = None
    program_path: str | None = None
    error: str | None = None
    failure_code: str | None = None
    artifact: StagedArtifact | None = None
    artifact_kind: ArtifactKind = "check"
    source_kind: SourceKind = "policy"
    check_name: str | None = None

    @property
    def program(self) -> str | None:
        """Return the generated SMT-LIB program."""
        return self.smt2_program


class ProofOfThought:
    """High-level staged API for Z3-based reasoning."""

    def __init__(
        self,
        llm_client: Any,
        model: str = "gpt-5",
        backend: BackendType = "staged_smt2",
        max_attempts: int = 3,
        verify_timeout: int = 10000,
        optimize_timeout: int = 100000,
        cache_dir: str | None = None,
        z3_path: str = "z3",
        postprocessors: Sequence[str | Postprocessor] | None = None,
        postprocessor_configs: dict[str, dict] | None = None,
    ) -> None:
        """Initialize ProofOfThought.

        The public major-release contract is staged-first:
        - `backend="staged_smt2"` is the canonical backend
        - `backend="smt2"` is a compatibility alias to the same staged implementation
        - `backend="json"` is removed
        """
        if backend == "json":  # type: ignore[comparison-overlap]
            raise ValueError(JSON_BACKEND_REMOVAL_MESSAGE)

        self.requested_backend: BackendType = backend
        self.backend_type: BackendType = "staged_smt2"
        self.llm_client = llm_client
        self.model = model
        self.max_attempts = max_attempts
        self.cache_dir = cache_dir or os.path.join(os.getcwd(), "output")
        self.optimize_timeout = optimize_timeout

        os.makedirs(self.cache_dir, exist_ok=True)

        # Preserve the one-shot SMT-LIB generator for compatibility features such as
        # postprocessors that still operate on the high-level query surface.
        self.generator = Z3ProgramGenerator(llm_client=llm_client, model=model, backend="smt2")

        self.backend = StagedSMT2Backend(verify_timeout=verify_timeout, z3_path=z3_path)

        self.postprocessors: list[Postprocessor] = []
        if postprocessors:
            self.postprocessors = self._initialize_postprocessors(
                postprocessors, postprocessor_configs or {}
            )
            logger.info("Initialized %d postprocessors", len(self.postprocessors))

    def _initialize_postprocessors(
        self,
        postprocessors: Sequence[str | Postprocessor],
        configs: dict[str, dict],
    ) -> list[Postprocessor]:
        """Initialize postprocessor instances from names or objects."""
        from z3adapter.postprocessors.abstract import Postprocessor
        from z3adapter.postprocessors.registry import PostprocessorRegistry

        initialized = []
        for item in postprocessors:
            if isinstance(item, str):
                initialized.append(PostprocessorRegistry.get(item, **configs.get(item, {})))
            elif isinstance(item, Postprocessor):
                initialized.append(item)
            else:
                logger.warning("Invalid postprocessor %r; skipping", item)
        return initialized

    def _make_staged_generator(self, max_tokens: int = 4096) -> StagedGenerator:
        """Construct a staged generator bound to the configured LLM."""
        return StagedGenerator(
            _StagedPromptClient(
                llm_client=self.llm_client,
                model=self.model,
                max_completion_tokens=max_tokens,
            )
        )

    def create_artifact(
        self,
        *,
        text: str = "",
        question: str = "",
        scenario_text: str = "",
        metadata: dict[str, Any] | None = None,
        annotations: dict[str, Any] | None = None,
        artifact_kind: ArtifactKind = "check",
        source_kind: SourceKind = "policy",
        trace_entries: Sequence[ArtifactTraceEntry | dict[str, Any]] | None = None,
        parent_artifact_path: str | None = None,
    ) -> StagedArtifact:
        """Create a new staged artifact."""
        normalized_text = text or question
        normalized_trace_entries: list[ArtifactTraceEntry] = []
        for entry in trace_entries or []:
            if isinstance(entry, ArtifactTraceEntry):
                normalized_trace_entries.append(entry)
            else:
                normalized_trace_entries.append(ArtifactTraceEntry(**entry))

        return StagedArtifact(
            source_text=normalized_text,
            question=question,
            scenario_text=scenario_text,
            artifact_kind=artifact_kind,
            source_kind=source_kind,
            metadata=dict(metadata or {}),
            annotations=dict(annotations or {}),
            trace_entries=normalized_trace_entries,
            parent_artifact_path=parent_artifact_path,
            library_version=__version__,
        )

    def save_artifact(self, artifact: StagedArtifact, path: str | Path) -> StagedArtifact:
        """Persist an artifact to disk."""
        artifact.library_version = __version__
        artifact.save(path)
        return artifact

    def load_artifact(self, path: str | Path) -> StagedArtifact:
        """Load a persisted artifact from disk."""
        return StagedArtifact.load(path)

    def fork_artifact(
        self,
        artifact: StagedArtifact,
        *,
        artifact_kind: ArtifactKind | None = None,
        question: str | None = None,
        scenario_text: str | None = None,
        metadata_updates: dict[str, Any] | None = None,
    ) -> StagedArtifact:
        """Clone an artifact for a new branch of checks or audits."""
        cloned = artifact.clone(
            artifact_kind=artifact_kind or artifact.artifact_kind,
            parent_artifact_path=artifact.artifact_path,
        )
        cloned.clear_from_stage("scenario")
        if question is not None:
            cloned.question = question
        if scenario_text is not None:
            cloned.scenario_text = scenario_text
        if metadata_updates:
            cloned.metadata.update(metadata_updates)
        return cloned

    def add_trace_entry(
        self,
        artifact: StagedArtifact,
        content: str,
        *,
        entry_type: TraceEntryKind = "note",
        metadata: dict[str, Any] | None = None,
    ) -> StagedArtifact:
        """Attach a trace event to an artifact."""
        artifact.add_trace_entry(content, entry_type=entry_type, metadata=metadata)
        return artifact

    def _format_annotations(self, annotations: dict[str, Any]) -> str:
        """Format structured annotations for staged prompting."""
        if not annotations:
            return ""
        return json.dumps(annotations, indent=2, sort_keys=True)

    def _format_trace_entries(self, trace_entries: Sequence[ArtifactTraceEntry]) -> str:
        """Render trace entries as prompt-ready text."""
        if not trace_entries:
            return ""

        lines = []
        for index, entry in enumerate(trace_entries, start=1):
            line = f"{index}. [{entry.entry_type}] {entry.content.strip()}"
            if entry.metadata:
                line += f" | metadata={json.dumps(entry.metadata, sort_keys=True)}"
            lines.append(line)
        return "\n".join(lines)

    def _build_foundation_input(self, artifact: StagedArtifact) -> str:
        """Build the staged foundation input from source text and annotations."""
        sections = []
        if artifact.source_text.strip():
            sections.append(artifact.source_text.strip())
        annotations_block = self._format_annotations(artifact.annotations)
        if annotations_block:
            sections.append(f"Structured annotations:\n{annotations_block}")
        return "\n\n".join(section for section in sections if section).strip()

    def _build_check_input(self, artifact: StagedArtifact) -> str:
        """Build the staged scenario/query input from artifact state."""
        sections = []
        if artifact.question.strip():
            sections.append(f"Check objective:\n{artifact.question.strip()}")
        if artifact.scenario_text.strip():
            sections.append(f"Scenario details:\n{artifact.scenario_text.strip()}")
        trace_block = self._format_trace_entries(artifact.trace_entries)
        if trace_block:
            sections.append(f"Trace context:\n{trace_block}")
        return "\n\n".join(section for section in sections if section).strip()

    def _refresh_artifact_views(self, artifact: StagedArtifact, generator: StagedGenerator) -> None:
        """Update derived artifact fields from the current generator context."""
        artifact.context = generator.get_context().to_dict()
        artifact.context_summary = generator.get_context_summary()
        artifact.foundation_smt2 = generator.compose_context_program(
            include_scenario=False,
            include_queries=False,
        )
        artifact.program_smt2 = generator.compose_context_program(
            include_scenario=bool(artifact.stage_outputs.get("scenario")),
            include_queries=bool(artifact.stage_outputs.get("query")),
        )
        artifact.library_version = __version__

    def _run_stage_range(
        self,
        artifact: StagedArtifact,
        *,
        start_stage: StageName,
        through_stage: StageName,
        max_tokens: int = 4096,
        artifact_path: str | Path | None = None,
    ) -> StagedArtifact:
        """Run a contiguous set of stages against an artifact."""
        start_index = STAGE_ORDER.index(start_stage)
        end_index = STAGE_ORDER.index(through_stage)
        if end_index < start_index:
            raise ValueError("through_stage must not come before start_stage")
        foundation_input = self._build_foundation_input(artifact) or artifact.source_text or artifact.question
        check_input = self._build_check_input(artifact)
        if through_stage in ("scenario", "query") and not check_input:
            raise ValueError(f"Artifact question is required to run stage '{through_stage}'")

        artifact.clear_from_stage(start_stage)

        generator = self._make_staged_generator(max_tokens=max_tokens)
        if artifact.stage_outputs:
            generator.rebuild_context_from_outputs(artifact.stage_outputs)

        selected_stages = list(STAGE_ORDER[start_index : end_index + 1])
        result = generator.generate(
            text=foundation_input,
            question=check_input,
            stages=selected_stages,
            reset_context=False,
        )

        if result.errors:
            raise RuntimeError("; ".join(result.errors))

        artifact.stage_outputs.update(result.stage_outputs)
        self._refresh_artifact_views(artifact, generator)

        if artifact_path is not None:
            self.save_artifact(artifact, artifact_path)

        return artifact

    def run_stage(
        self,
        artifact: StagedArtifact,
        stage_name: StageName,
        *,
        rerun_downstream: bool = True,
        max_tokens: int = 4096,
        artifact_path: str | Path | None = None,
    ) -> StagedArtifact:
        """Run one stage, optionally cascading through downstream stages."""
        if rerun_downstream:
            if self._build_check_input(artifact):
                target_stage: StageName = "query"
            elif STAGE_ORDER.index(stage_name) <= STAGE_ORDER.index("knowledge_base"):
                target_stage = "knowledge_base"
            else:
                target_stage = stage_name
        else:
            target_stage = stage_name
        return self._run_stage_range(
            artifact,
            start_stage=stage_name,
            through_stage=target_stage,
            max_tokens=max_tokens,
            artifact_path=artifact_path,
        )

    def run_through_stage(
        self,
        artifact: StagedArtifact,
        stage_name: StageName,
        *,
        from_stage: StageName = "sorts",
        max_tokens: int = 4096,
        artifact_path: str | Path | None = None,
    ) -> StagedArtifact:
        """Run stages from `from_stage` through `stage_name`."""
        return self._run_stage_range(
            artifact,
            start_stage=from_stage,
            through_stage=stage_name,
            max_tokens=max_tokens,
            artifact_path=artifact_path,
        )

    def build_artifact(
        self,
        *,
        text: str,
        question: str,
        through_stage: StageName = "query",
        metadata: dict[str, Any] | None = None,
        max_tokens: int = 4096,
        artifact_path: str | Path | None = None,
    ) -> StagedArtifact:
        """Create and populate a staged artifact through the requested stage."""
        artifact = self.create_artifact(
            text=text,
            question=question,
            metadata=metadata,
            artifact_kind="check",
        )
        return self.run_through_stage(
            artifact,
            through_stage,
            max_tokens=max_tokens,
            artifact_path=artifact_path,
        )

    def build_foundation(
        self,
        *,
        text: str,
        source_kind: SourceKind = "policy",
        annotations: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        through_stage: StageName = "knowledge_base",
        max_tokens: int = 4096,
        artifact_path: str | Path | None = None,
    ) -> StagedArtifact:
        """Build a reusable foundation artifact through knowledge-base stages."""
        artifact = self.create_artifact(
            text=text,
            metadata=metadata,
            annotations=annotations,
            artifact_kind="foundation",
            source_kind=source_kind,
        )
        return self.run_through_stage(
            artifact,
            through_stage,
            max_tokens=max_tokens,
            artifact_path=artifact_path,
        )

    def _record_check_result(
        self,
        artifact: StagedArtifact,
        result: QueryResult,
        *,
        check_name: str | None = None,
        check_metadata: dict[str, Any] | None = None,
        ) -> None:
        """Record the executed check on the artifact."""
        artifact.record_check(
            question=artifact.question,
            scenario_text=artifact.scenario_text,
            name=check_name or "",
            metadata=check_metadata,
            answer=result.answer,
            success=result.success,
            failure_code=result.failure_code,
            program_path=result.program_path,
        )
        result.artifact = artifact
        result.check_name = check_name
        result.artifact_kind = artifact.artifact_kind
        result.source_kind = artifact.source_kind
        if result.program_path is None:
            result.program_path = artifact.execution.program_path

    def _resolve_artifact_save_destination(
        self,
        artifact: StagedArtifact,
        *,
        save_artifact: bool,
        artifact_path: str | Path | None,
    ) -> Path | None:
        """Resolve where an artifact should be persisted, if at all."""
        if artifact_path is not None:
            return Path(artifact_path)
        if save_artifact and artifact.artifact_path:
            return Path(artifact.artifact_path)
        return None

    def _persist_artifact_if_requested(
        self,
        artifact: StagedArtifact,
        *,
        save_artifact: bool,
        artifact_path: str | Path | None,
    ) -> None:
        """Persist an artifact when a save destination is available."""
        destination = self._resolve_artifact_save_destination(
            artifact,
            save_artifact=save_artifact,
            artifact_path=artifact_path,
        )
        if destination is not None:
            self.save_artifact(artifact, destination)

    def _prepare_check_artifact(
        self,
        artifact: StagedArtifact,
        *,
        question: str,
        scenario_text: str,
        trace_entries: Sequence[ArtifactTraceEntry | dict[str, Any]] | None,
    ) -> StagedArtifact:
        """Create a working artifact for one executed check without mutating the input."""
        working_artifact = artifact.clone(parent_artifact_path=artifact.artifact_path)
        working_artifact.question = question
        working_artifact.scenario_text = scenario_text

        normalized_trace_entries: list[ArtifactTraceEntry] = []
        for entry in trace_entries or []:
            if isinstance(entry, ArtifactTraceEntry):
                normalized_trace_entries.append(entry)
            else:
                normalized_trace_entries.append(ArtifactTraceEntry(**entry))
        working_artifact.trace_entries.extend(normalized_trace_entries)
        working_artifact.artifact_kind = "audit" if working_artifact.trace_entries else "check"
        return working_artifact

    def _merge_postprocessed_result(
        self,
        base_result: QueryResult,
        enhanced_result: QueryResult,
    ) -> QueryResult:
        """Merge staged metadata back onto a postprocessed result."""
        artifact = enhanced_result.artifact or base_result.artifact
        return replace(
            enhanced_result,
            question=base_result.question,
            num_attempts=enhanced_result.num_attempts or base_result.num_attempts,
            backend=base_result.backend,
            program_format=enhanced_result.program_format or base_result.program_format,
            smt2_program=enhanced_result.smt2_program or base_result.smt2_program,
            program_path=enhanced_result.program_path or base_result.program_path,
            error=enhanced_result.error if enhanced_result.error is not None else base_result.error,
            failure_code=(
                enhanced_result.failure_code
                if enhanced_result.failure_code is not None
                else base_result.failure_code
            ),
            artifact=artifact,
            artifact_kind=artifact.artifact_kind if artifact is not None else base_result.artifact_kind,
            source_kind=artifact.source_kind if artifact is not None else base_result.source_kind,
            check_name=enhanced_result.check_name or base_result.check_name,
        )

    def run_check(
        self,
        artifact: StagedArtifact,
        *,
        question: str,
        scenario_text: str = "",
        check_name: str | None = None,
        check_metadata: dict[str, Any] | None = None,
        trace_entries: Sequence[ArtifactTraceEntry | dict[str, Any]] | None = None,
        save_program: bool = False,
        program_path: str | None = None,
        save_artifact: bool = False,
        artifact_path: str | Path | None = None,
        enable_postprocessing: bool = True,
        max_tokens: int = 4096,
    ) -> QueryResult:
        """Run a staged verification check against an existing artifact foundation."""
        working_artifact = self._prepare_check_artifact(
            artifact,
            question=question,
            scenario_text=scenario_text,
            trace_entries=trace_entries,
        )
        self.run_stage(
            working_artifact,
            "scenario",
            rerun_downstream=True,
            max_tokens=max_tokens,
        )
        result = self.execute_artifact(
            working_artifact,
            save_program=save_program,
            program_path=program_path,
            enable_postprocessing=enable_postprocessing,
        )
        self._record_check_result(
            working_artifact,
            result,
            check_name=check_name,
            check_metadata=check_metadata,
        )
        self._persist_artifact_if_requested(
            working_artifact,
            save_artifact=save_artifact,
            artifact_path=artifact_path,
        )
        return result

    def execute_artifact(
        self,
        artifact: StagedArtifact,
        *,
        save_program: bool = False,
        program_path: str | None = None,
        save_artifact: bool = False,
        artifact_path: str | Path | None = None,
        enable_postprocessing: bool = True,
    ) -> QueryResult:
        """Execute the current staged artifact against Z3."""
        if not artifact.program_smt2:
            raise ValueError("Artifact does not contain a composed SMT-LIB program to execute.")

        reported_program_path: str | None = None
        if save_program or program_path:
            destination = Path(program_path or os.path.join(self.cache_dir, "artifact.smt2"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(artifact.program_smt2, encoding="utf-8")
            reported_program_path = str(destination)
            verify_result = self.backend.execute(reported_program_path)
        else:
            verify_result = self.backend.execute_from_string(artifact.program_smt2)

        artifact.execution = ArtifactExecution(
            success=verify_result.success,
            answer=verify_result.answer,
            sat_count=verify_result.sat_count,
            unsat_count=verify_result.unsat_count,
            output=verify_result.output,
            error=verify_result.error,
            failure_code=verify_result.failure_code,
            program_path=reported_program_path,
        )

        if save_artifact or artifact_path:
            destination = artifact_path or artifact.artifact_path
            if destination:
                self.save_artifact(artifact, destination)

        result = QueryResult(
            question=artifact.question,
            answer=verify_result.answer,
            sat_count=verify_result.sat_count,
            unsat_count=verify_result.unsat_count,
            output=verify_result.output,
            success=verify_result.success and verify_result.answer is not None,
            num_attempts=1,
            backend=self.backend_type,
            program_format="smt2",
            smt2_program=artifact.program_smt2,
            program_path=reported_program_path,
            error=verify_result.error,
            failure_code=verify_result.failure_code,
            artifact=artifact,
            artifact_kind=artifact.artifact_kind,
            source_kind=artifact.source_kind,
        )

        if enable_postprocessing and self.postprocessors and result.success:
            return self._apply_postprocessors(
                question=artifact.question,
                initial_result=result,
                temperature=0.1,
                max_tokens=16384,
            )

        return result

    def query(
        self,
        question: str,
        text: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 16384,
        save_program: bool = False,
        program_path: str | None = None,
        enable_postprocessing: bool = True,
        save_artifact: bool = False,
        artifact_path: str | Path | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Answer a question using the staged SMT-LIB pipeline.

        If `text` is omitted, the question itself is used as the one-shot staged input.
        """
        del temperature  # GPT-5 style chat calls do not expose a stable temperature control here.

        logger.info("Processing question via staged pipeline: %s", question)

        error_trace: str | None = None
        last_failure_code: str | None = None
        last_artifact: StagedArtifact | None = None

        for attempt in range(1, self.max_attempts + 1):
            logger.info("Attempt %d/%d", attempt, self.max_attempts)
            artifact = self.create_artifact(
                text=text or question,
                question=question,
                metadata=metadata,
                artifact_kind="check",
            )
            last_artifact = artifact

            try:
                self.run_through_stage(
                    artifact,
                    "query",
                    max_tokens=max_tokens,
                )
                result = self.execute_artifact(
                    artifact,
                    save_program=save_program,
                    program_path=program_path,
                    enable_postprocessing=False,
                )
                result.num_attempts = attempt

                if not result.success:
                    error_trace = result.error or "Z3 verification failed"
                    last_failure_code = result.failure_code or "verification_failed"
                    logger.warning("Verification failed: %s", error_trace)
                    continue

                if result.answer is None:
                    error_trace = (
                        "Ambiguous verification result: "
                        f"SAT={result.sat_count}, UNSAT={result.unsat_count}\n"
                        f"Output:\n{result.output}"
                    )
                    last_failure_code = "ambiguous_verification_result"
                    logger.warning("Ambiguous result: %s", error_trace)
                    continue

                if enable_postprocessing and self.postprocessors:
                    result = self._apply_postprocessors(
                        question=question,
                        initial_result=result,
                        temperature=0.1,
                        max_tokens=max_tokens,
                    )
                    result.num_attempts = attempt

                self._record_check_result(last_artifact, result)
                self._persist_artifact_if_requested(
                    last_artifact,
                    save_artifact=save_artifact,
                    artifact_path=artifact_path,
                )
                return result

            except Exception as exc:
                error_trace = f"Error: {exc}\n{traceback.format_exc()}"
                last_failure_code = "unexpected_exception"
                logger.error("Exception on attempt %d: %s", attempt, error_trace)

        logger.error("Failed to answer question after %d attempts", self.max_attempts)
        final_result = QueryResult(
            question=question,
            answer=None,
            sat_count=last_artifact.execution.sat_count if last_artifact else 0,
            unsat_count=last_artifact.execution.unsat_count if last_artifact else 0,
            output=last_artifact.execution.output if last_artifact else "",
            success=False,
            num_attempts=self.max_attempts,
            backend=self.backend_type,
            program_format="smt2" if last_artifact and last_artifact.program_smt2 else None,
            smt2_program=last_artifact.program_smt2 if last_artifact else None,
            program_path=last_artifact.execution.program_path if last_artifact else None,
            error=f"Failed after {self.max_attempts} attempts. Last error: {error_trace}",
            failure_code=last_failure_code or "query_failed",
            artifact=last_artifact,
            artifact_kind=last_artifact.artifact_kind if last_artifact else "check",
            source_kind=last_artifact.source_kind if last_artifact else "policy",
        )
        if last_artifact is not None:
            self._record_check_result(last_artifact, final_result)
            self._persist_artifact_if_requested(
                last_artifact,
                save_artifact=save_artifact,
                artifact_path=artifact_path,
            )
        return final_result

    def _apply_postprocessors(
        self,
        question: str,
        initial_result: QueryResult,
        temperature: float,
        max_tokens: int,
    ) -> QueryResult:
        """Apply all configured postprocessors to improve the result."""
        current_result = initial_result

        for postprocessor in self.postprocessors:
            logger.info("Applying postprocessor: %s", postprocessor.name)

            try:
                enhanced_result = postprocessor.process(
                    question=question,
                    initial_result=current_result,
                    generator=self.generator,
                    backend=self.backend,
                    llm_client=self.llm_client,
                    cache_dir=self.cache_dir,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                if enhanced_result.success:
                    current_result = self._merge_postprocessed_result(
                        current_result,
                        enhanced_result,
                    )
                    logger.info(
                        "Postprocessor %s completed. Answer: %s",
                        postprocessor.name,
                        current_result.answer,
                    )
                else:
                    logger.warning(
                        "Postprocessor %s failed, keeping previous result",
                        postprocessor.name,
                    )

            except Exception as exc:
                logger.error("Error in postprocessor %s: %s", postprocessor.name, exc)

        return current_result
