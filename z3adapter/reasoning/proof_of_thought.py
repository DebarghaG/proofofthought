"""ProofOfThought: staged-first API for Z3-based reasoning."""

from __future__ import annotations

import json
import logging
import os
import re
import traceback
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from z3adapter._version import __version__
from z3adapter.backends.smt2 import STAGE_ORDER, StagedGenerator
from z3adapter.backends.smt2.generator import VerificationMode
from z3adapter.backends.smt2.backend import StagedSMT2Backend
from z3adapter.backends.smt2.prompts import BACKGROUND_KNOWLEDGE_COMMENT
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
RigorLevel = Literal["strict_grounded", "background_informed"]

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
    background_knowledge_used: bool = False
    rigor_level: RigorLevel = "strict_grounded"

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
        verification_mode: VerificationMode = "entailment",
        max_attempts: int = 3,
        max_stage_repairs: int = 1,
        max_solver_repairs: int = 1,
        require_grounding: bool = True,
        allow_background_knowledge: bool = False,
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
        self.verification_mode: VerificationMode = verification_mode
        self.llm_client = llm_client
        self.model = model
        self.max_attempts = max_attempts
        self.max_stage_repairs = max_stage_repairs
        self.max_solver_repairs = max_solver_repairs
        self.require_grounding = require_grounding
        self.allow_background_knowledge = allow_background_knowledge
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

    def _make_staged_generator(
        self,
        *,
        max_tokens: int = 4096,
        require_background_knowledge_tags: bool = False,
    ) -> StagedGenerator:
        """Construct a staged generator bound to the configured LLM."""
        return StagedGenerator(
            _StagedPromptClient(
                llm_client=self.llm_client,
                model=self.model,
                max_completion_tokens=max_tokens,
            ),
            verification_mode=self.verification_mode,
            max_stage_repairs=self.max_stage_repairs,
            allow_background_knowledge=self.allow_background_knowledge,
            require_background_knowledge_tags=require_background_knowledge_tags,
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
        normalized_trace_entries: list[ArtifactTraceEntry] = []
        for entry in trace_entries or []:
            if isinstance(entry, ArtifactTraceEntry):
                normalized_trace_entries.append(entry)
            else:
                normalized_trace_entries.append(ArtifactTraceEntry(**entry))

        return StagedArtifact(
            source_text=text,
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
        """Build the staged foundation input from source text and annotations.

        In background-knowledge mode, question-only checks still need the
        foundation stages to know what domain the model should formalize. We
        therefore pass the question as topic context, but only when no external
        grounding exists, and we state that the claim must not be asserted just
        because it appears in the question.
        """
        sections = []
        if artifact.source_text.strip():
            sections.append(artifact.source_text.strip())
        annotations_block = self._format_annotations(artifact.annotations)
        if annotations_block:
            sections.append(f"Structured annotations:\n{annotations_block}")
        if (
            self.allow_background_knowledge
            and not sections
            and artifact.question.strip()
        ):
            sections.append(
                "Verification question context for selecting relevant background knowledge.\n"
                "There is no external grounding for this run, so every asserted fact or rule "
                "must be explicitly marked with `; background_knowledge`.\n"
                "Do not assert the question's claim merely because it appears here:\n"
                f"{artifact.question.strip()}"
            )
        return "\n\n".join(section for section in sections if section).strip()

    def _build_scenario_input(self, artifact: StagedArtifact) -> str:
        """Build the scenario-stage input from artifact state."""
        sections = []
        if artifact.scenario_text.strip():
            sections.append(f"Scenario details:\n{artifact.scenario_text.strip()}")
        trace_block = self._format_trace_entries(artifact.trace_entries)
        if trace_block:
            sections.append(f"Trace context:\n{trace_block}")
        return "\n\n".join(section for section in sections if section).strip()

    def _build_query_input(self, artifact: StagedArtifact) -> str:
        """Build the query-stage input from artifact state."""
        return artifact.question.strip()

    def _has_grounding_inputs(self, artifact: StagedArtifact) -> bool:
        """Return whether the artifact has external grounding beyond the bare question.

        This intentionally tracks only externally supplied evidence. Generated
        stage outputs do not count here: otherwise a question-only run could
        "bootstrap" its own invented world model and then pass the grounding
        check simply because later stages emitted assertions.
        """
        if artifact.source_text.strip():
            return True
        if artifact.annotations:
            return True
        if artifact.trace_entries:
            return True
        return False

    def _requires_background_knowledge_tags(self, artifact: StagedArtifact) -> bool:
        """Return whether this artifact must tag every asserted premise.

        This is the narrow mode used for datasets like StrategyQA: no external
        text is available, but we still want to permit common-sense premises as
        long as the artifact explicitly marks them as model-side background
        knowledge instead of presenting them as grounded facts.
        """
        return self.allow_background_knowledge and not self._has_grounding_inputs(artifact)

    def _iter_assertion_codes(self, artifact: StagedArtifact) -> list[str]:
        """Collect assertion code strings from the staged context snapshot."""
        context = artifact.context or {}
        codes: list[str] = []
        for section_name in ("kb_assertions", "rules", "scenario_assertions"):
            section = context.get(section_name, {})
            if not isinstance(section, dict):
                continue
            for payload in section.values():
                if not isinstance(payload, dict):
                    continue
                code = payload.get("smt_expr") or payload.get("smt_code") or ""
                if code:
                    codes.append(str(code))
        return codes

    def _has_background_knowledge_assertions(self, artifact: StagedArtifact) -> bool:
        """Return whether the artifact contains explicitly tagged background knowledge."""
        context = artifact.context or {}
        for section_name in ("kb_assertions", "rules", "scenario_assertions"):
            section = context.get(section_name, {})
            if not isinstance(section, dict):
                continue
            for payload in section.values():
                if not isinstance(payload, dict):
                    continue
                if bool(payload.get("background_knowledge", False)):
                    return True
                smt_code = str(payload.get("smt_code") or "")
                if "; background_knowledge" in smt_code.lower():
                    return True
        return False

    def _rigor_for_artifact(self, artifact: StagedArtifact) -> tuple[bool, RigorLevel]:
        """Classify whether the current proof relies on model background knowledge."""
        uses_background_knowledge = self._has_background_knowledge_assertions(artifact)
        if uses_background_knowledge:
            return True, "background_informed"
        return False, "strict_grounded"

    def _is_trivial_assertion(self, assertion_code: str) -> bool:
        """Identify assertions that provide no real support."""
        compact = re.sub(r"\s+", " ", assertion_code).strip()
        if compact.lower() == "(assert true)":
            return True
        return bool(
            re.fullmatch(r"\(assert\s+\(=\s+([^\s()]+)\s+\1\)\s*\)", compact)
        )

    def _grounding_failure(self, artifact: StagedArtifact) -> tuple[str, str] | None:
        """Return a machine-readable grounding failure, if any.

        The default staged product is a grounded verifier, not an open-world QA
        engine. Without this guard, question-only tasks such as StrategyQA tend
        to produce fabricated miniature world models that look formal but are
        not actually justified by source evidence.
        """
        if not self.require_grounding:
            return None

        has_grounding_inputs = self._has_grounding_inputs(artifact)
        has_background_knowledge = self._has_background_knowledge_assertions(artifact)

        if not has_grounding_inputs and not (
            self.allow_background_knowledge and has_background_knowledge
        ):
            return (
                "This verification request has no grounded source text, annotations, or trace context. "
                "Provide supporting evidence, or enable and explicitly tag background knowledge assertions.",
                "unsupported_without_grounding",
            )

        assertion_codes = self._iter_assertion_codes(artifact)
        if assertion_codes and not any(
            not self._is_trivial_assertion(assertion_code) for assertion_code in assertion_codes
        ):
            return (
                "The generated world model is vacuous and does not contain substantive grounded assertions.",
                "vacuous_world_model",
            )

        return None

    def _failure_code_for_exception(
        self,
        artifact: StagedArtifact | None,
        exc: Exception,
    ) -> str:
        """Map runtime exceptions onto stable failure codes.

        Tag-compliance errors are expected operational failures in
        background-knowledge mode, not generic crashes. Surfacing them with a
        dedicated code makes benchmark analysis much clearer.
        """
        if artifact is not None and self._requires_background_knowledge_tags(artifact):
            if BACKGROUND_KNOWLEDGE_COMMENT in str(exc):
                return "background_knowledge_tags_missing"
        return "unexpected_exception"

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
        """Run a contiguous set of stages against an artifact.

        We run foundation, scenario, and query as separate prompt phases on
        purpose. Earlier versions let the combined question leak into the
        scenario-building stage, which caused the claim itself to be asserted as
        world state and artificially inflated benchmark results.
        """
        start_index = STAGE_ORDER.index(start_stage)
        end_index = STAGE_ORDER.index(through_stage)
        if end_index < start_index:
            raise ValueError("through_stage must not come before start_stage")
        foundation_input = self._build_foundation_input(artifact) or artifact.source_text
        scenario_input = self._build_scenario_input(artifact)
        query_input = self._build_query_input(artifact)
        if through_stage == "query" and not query_input:
            raise ValueError("Artifact question is required to run stage 'query'")

        artifact.clear_from_stage(start_stage)

        generator = self._make_staged_generator(
            max_tokens=max_tokens,
            require_background_knowledge_tags=self._requires_background_knowledge_tags(artifact),
        )
        if artifact.stage_outputs:
            generator.rebuild_context_from_outputs(artifact.stage_outputs)

        selected_stages = list(STAGE_ORDER[start_index : end_index + 1])
        foundation_stages = [
            stage_name
            for stage_name in selected_stages
            if stage_name in ("sorts", "functions", "constants", "knowledge_base")
        ]
        accumulated_outputs: dict[str, str] = {}
        accumulated_errors: list[str] = []

        if foundation_stages:
            result = generator.generate(
                text=foundation_input,
                question="",
                stages=foundation_stages,
                reset_context=False,
            )
            accumulated_outputs.update(result.stage_outputs)
            accumulated_errors.extend(result.errors)

        if "scenario" in selected_stages and scenario_input:
            result = generator.generate(
                text=foundation_input,
                question=scenario_input,
                stages=["scenario"],
                reset_context=False,
            )
            accumulated_outputs.update(result.stage_outputs)
            accumulated_errors.extend(result.errors)

        if "query" in selected_stages:
            result = generator.generate(
                text=foundation_input,
                question=query_input,
                stages=["query"],
                reset_context=False,
            )
            accumulated_outputs.update(result.stage_outputs)
            accumulated_errors.extend(result.errors)

        if accumulated_errors:
            raise RuntimeError("; ".join(accumulated_errors))

        artifact.stage_outputs.update(accumulated_outputs)
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
            if self._build_query_input(artifact):
                target_stage: StageName = "query"
            elif self._build_scenario_input(artifact):
                target_stage = "scenario"
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
            background_knowledge_used=result.background_knowledge_used,
            rigor_level=result.rigor_level,
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

    def _split_one_shot_prompt(self, prompt: str) -> tuple[str, str]:
        """Split legacy one-shot prompts into foundation text and check question.

        This exists to preserve compatibility with older benchmark and example
        inputs that were authored as one combined string. We prefer explicit
        `text=` plus `question=`, but this split keeps the staged pipeline from
        incorrectly treating the verification claim itself as background theory.
        """
        stripped = prompt.strip()
        split_markers = (
            r"\n\s*\nQuestion:\s*",
            r"\n\s*\nIs the following statement true or false\?\s*",
            (
                r"\n\s*\nAssuming all premises are true, is the following statement true or false\?"
                r"\s*\n\s*\nStatement:\s*"
            ),
            r"\n\s*\nStatement:\s*",
        )

        for marker in split_markers:
            match = re.search(marker, stripped, flags=re.IGNORECASE)
            if match:
                source_text = stripped[: match.start()].strip()
                question = stripped[match.end() :].strip()
                if source_text and question:
                    return source_text, question

        return "", stripped

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
            background_knowledge_used=(
                enhanced_result.background_knowledge_used or base_result.background_knowledge_used
            ),
            rigor_level=(
                enhanced_result.rigor_level
                if enhanced_result.background_knowledge_used
                else base_result.rigor_level
            ),
        )

    def _repair_smt2_program(
        self,
        artifact: StagedArtifact,
        *,
        program: str,
        solver_error: str,
        max_tokens: int = 4096,
    ) -> str:
        """Ask the LLM to repair a full SMT-LIB program after a solver error."""
        prompt_sections = [
            "You are repairing a complete SMT-LIB program after Z3 reported an error.",
            "Return ONLY the corrected complete SMT-LIB program. No explanations, no markdown.",
            "Preserve the intended verification semantics and keep the verification mode comment if present.",
            "Use valid SMT-LIB prefix syntax.",
            "Reference zero-arity constants without parentheses.",
            "Do not add unsupported facts or symbols that are not grounded in the source text, scenario, existing program, or explicitly tagged background knowledge.",
            f"Verification question:\n{artifact.question or '(none)'}",
        ]
        if artifact.source_text.strip():
            prompt_sections.append(f"Source text:\n{artifact.source_text.strip()}")
        if artifact.scenario_text.strip():
            prompt_sections.append(f"Scenario text:\n{artifact.scenario_text.strip()}")
        prompt_sections.extend(
            [
                f"Z3 error output:\n{solver_error}",
                f"Broken SMT-LIB program:\n{program}",
                "Correct the SMT-LIB program.",
            ]
        )
        repair_prompt = "\n\n".join(prompt_sections)
        repaired_program = _StagedPromptClient(
            llm_client=self.llm_client,
            model=self.model,
            max_completion_tokens=max_tokens,
        ).generate(repair_prompt)
        repaired_program = repaired_program.strip()
        if not repaired_program:
            raise RuntimeError("Solver repair prompt returned an empty SMT-LIB program")
        return repaired_program

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
        """Execute the current staged artifact against Z3.

        The ordering here is deliberate:

        1. optionally persist the exact SMT program we are about to execute
        2. reject unsupported or vacuous world models before the solver runs
        3. attempt solver execution
        4. repair the full program only if Z3 reports a concrete solver error

        That split keeps "bad formalization" distinct from "bad SMT syntax".
        """
        if not artifact.program_smt2:
            raise ValueError("Artifact does not contain a composed SMT-LIB program to execute.")

        current_program = artifact.program_smt2
        background_knowledge_used, rigor_level = self._rigor_for_artifact(artifact)
        reported_program_path: str | None = None
        if save_program or program_path:
            destination = Path(program_path or os.path.join(self.cache_dir, "artifact.smt2"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(current_program, encoding="utf-8")
            reported_program_path = str(destination)

        grounding_failure = self._grounding_failure(artifact)
        if grounding_failure is not None:
            error_message, failure_code = grounding_failure
            artifact.execution = ArtifactExecution(
                success=False,
                answer=None,
                sat_count=0,
                unsat_count=0,
                output="",
                error=error_message,
                failure_code=failure_code,
                program_path=reported_program_path,
                background_knowledge_used=background_knowledge_used,
                rigor_level=rigor_level,
            )

            result = QueryResult(
                question=artifact.question,
                answer=None,
                sat_count=0,
                unsat_count=0,
                output="",
                success=False,
                num_attempts=1,
                backend=self.backend_type,
                program_format="smt2",
                smt2_program=current_program,
                program_path=reported_program_path,
                error=error_message,
                failure_code=failure_code,
                artifact=artifact,
                artifact_kind=artifact.artifact_kind,
                source_kind=artifact.source_kind,
                background_knowledge_used=background_knowledge_used,
                rigor_level=rigor_level,
            )

            if save_artifact or artifact_path:
                destination = artifact_path or artifact.artifact_path
                if destination:
                    self.save_artifact(artifact, destination)

            return result

        verify_result = self.backend.execute_from_string(current_program)
        repairs_remaining = self.max_solver_repairs

        while repairs_remaining > 0 and verify_result.failure_code == "solver_error":
            repaired_program = self._repair_smt2_program(
                artifact,
                program=current_program,
                solver_error=verify_result.error or verify_result.output,
            )
            if repaired_program.strip() == current_program.strip():
                break
            current_program = repaired_program
            artifact.program_smt2 = current_program
            verify_result = self.backend.execute_from_string(current_program)
            repairs_remaining -= 1

        artifact.program_smt2 = current_program
        if reported_program_path is not None:
            Path(reported_program_path).write_text(current_program, encoding="utf-8")

        artifact.execution = ArtifactExecution(
            success=verify_result.success,
            answer=verify_result.answer,
            sat_count=verify_result.sat_count,
            unsat_count=verify_result.unsat_count,
            output=verify_result.output,
            error=verify_result.error,
            failure_code=verify_result.failure_code,
            program_path=reported_program_path,
            background_knowledge_used=background_knowledge_used,
            rigor_level=rigor_level,
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
            smt2_program=current_program,
            program_path=reported_program_path,
            error=verify_result.error,
            failure_code=verify_result.failure_code,
            artifact=artifact,
            artifact_kind=artifact.artifact_kind,
            source_kind=artifact.source_kind,
            background_knowledge_used=background_knowledge_used,
            rigor_level=rigor_level,
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

        `query()` remains the short path, but it still follows the staged flow.
        If callers omit `text`, we first try to split legacy "context + question"
        combined prompts. When that split yields only a bare question, grounded
        mode now fails fast instead of silently treating the question as source
        evidence.
        """
        del temperature  # GPT-5 style chat calls do not expose a stable temperature control here.

        logger.info("Processing question via staged pipeline: %s", question)
        source_text = text
        normalized_question = question
        if source_text is None:
            source_text, normalized_question = self._split_one_shot_prompt(question)

        # Build the first artifact before any stage work so grounding checks and
        # later retries all start from the same normalized inputs.
        preflight_artifact = self.create_artifact(
            text=source_text or "",
            question=normalized_question,
            metadata=metadata,
            artifact_kind="check",
        )

        if (
            self.require_grounding
            and not self.allow_background_knowledge
            and not self._has_grounding_inputs(preflight_artifact)
        ):
            artifact = preflight_artifact
            error_message = (
                "This verification request has no grounded source text, annotations, or trace context. "
                "Provide supporting evidence, or enable and explicitly tag background knowledge assertions."
            )
            artifact.execution = ArtifactExecution(
                success=False,
                answer=None,
                sat_count=0,
                unsat_count=0,
                output="",
                error=error_message,
                failure_code="unsupported_without_grounding",
                background_knowledge_used=False,
                rigor_level="strict_grounded",
            )
            result = QueryResult(
                question=normalized_question,
                answer=None,
                sat_count=0,
                unsat_count=0,
                output="",
                success=False,
                num_attempts=1,
                backend=self.backend_type,
                error=error_message,
                failure_code="unsupported_without_grounding",
                artifact=artifact,
                artifact_kind=artifact.artifact_kind,
                source_kind=artifact.source_kind,
                background_knowledge_used=False,
                rigor_level="strict_grounded",
            )
            self._record_check_result(artifact, result)
            self._persist_artifact_if_requested(
                artifact,
                save_artifact=save_artifact,
                artifact_path=artifact_path,
            )
            return result

        error_trace: str | None = None
        last_failure_code: str | None = None
        last_artifact: StagedArtifact | None = None

        for attempt in range(1, self.max_attempts + 1):
            logger.info("Attempt %d/%d", attempt, self.max_attempts)
            artifact = preflight_artifact.clone() if attempt == 1 else self.create_artifact(
                text=source_text or "",
                question=normalized_question,
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
                        question=normalized_question,
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
                last_failure_code = self._failure_code_for_exception(artifact, exc)
                logger.error("Exception on attempt %d: %s", attempt, error_trace)

        logger.error("Failed to answer question after %d attempts", self.max_attempts)
        final_result = QueryResult(
            question=normalized_question,
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
            background_knowledge_used=(
                last_artifact.execution.background_knowledge_used if last_artifact else False
            ),
            rigor_level=(
                last_artifact.execution.rigor_level if last_artifact else "strict_grounded"
            ),
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
