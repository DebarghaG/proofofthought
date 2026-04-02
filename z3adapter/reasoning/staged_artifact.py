"""Persistent staged artifact model for the staged SMT-LIB workflow."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from z3adapter._version import __version__

StageName = Literal["sorts", "functions", "constants", "knowledge_base", "scenario", "query"]
ArtifactKind = Literal["foundation", "check", "audit"]
SourceKind = Literal["policy", "document", "code", "mixed"]
TraceEntryKind = Literal["observation", "action", "tool_call", "tool_result", "note"]
STAGE_ORDER: tuple[StageName, ...] = (
    "sorts",
    "functions",
    "constants",
    "knowledge_base",
    "scenario",
    "query",
)
STAGED_ARTIFACT_SCHEMA_VERSION = 2


@dataclass
class ArtifactExecution:
    """Execution details for a staged artifact."""

    success: bool = False
    answer: bool | None = None
    sat_count: int = 0
    unsat_count: int = 0
    output: str = ""
    error: str | None = None
    failure_code: str | None = None
    program_path: str | None = None


@dataclass
class ArtifactTraceEntry:
    """Trace entry attached to a staged artifact."""

    entry_type: TraceEntryKind = "note"
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArtifactCheck:
    """Metadata and outcome for one executed check."""

    name: str = ""
    question: str = ""
    scenario_text: str = ""
    trace_entry_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    answer: bool | None = None
    success: bool = False
    failure_code: str | None = None
    program_path: str | None = None


@dataclass
class StagedArtifact:
    """Durable staged state that can be resumed across sessions."""

    source_text: str = ""
    question: str = ""
    scenario_text: str = ""
    artifact_kind: ArtifactKind = "check"
    source_kind: SourceKind = "policy"
    metadata: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)
    trace_entries: list[ArtifactTraceEntry] = field(default_factory=list)
    check_history: list[ArtifactCheck] = field(default_factory=list)
    stage_outputs: dict[str, str] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    context_summary: str = ""
    foundation_smt2: str = ""
    program_smt2: str = ""
    execution: ArtifactExecution = field(default_factory=ArtifactExecution)
    artifact_path: str | None = None
    parent_artifact_path: str | None = None
    backend: str = "staged_smt2"
    artifact_schema_version: int = STAGED_ARTIFACT_SCHEMA_VERSION
    library_version: str = __version__

    @property
    def completed_stages(self) -> list[StageName]:
        """Return completed stages in canonical order."""
        return [stage for stage in STAGE_ORDER if self.stage_outputs.get(stage)]

    @property
    def latest_check(self) -> ArtifactCheck | None:
        """Return the most recent recorded check."""
        if not self.check_history:
            return None
        return self.check_history[-1]

    def clear_from_stage(self, stage_name: StageName) -> None:
        """Invalidate a stage and all downstream state."""
        start_index = STAGE_ORDER.index(stage_name)
        for downstream_stage in STAGE_ORDER[start_index:]:
            self.stage_outputs.pop(downstream_stage, None)

        self.context = {}
        self.context_summary = ""
        self.foundation_smt2 = ""
        self.program_smt2 = ""
        self.execution = ArtifactExecution()

    def add_trace_entry(
        self,
        content: str,
        *,
        entry_type: TraceEntryKind = "note",
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactTraceEntry:
        """Append a trace entry and promote the artifact to audit mode."""
        entry = ArtifactTraceEntry(
            entry_type=entry_type,
            content=content,
            metadata=dict(metadata or {}),
        )
        self.trace_entries.append(entry)
        self.artifact_kind = "audit"
        return entry

    def record_check(
        self,
        *,
        question: str,
        scenario_text: str = "",
        name: str = "",
        metadata: dict[str, Any] | None = None,
        answer: bool | None = None,
        success: bool = False,
        failure_code: str | None = None,
        program_path: str | None = None,
    ) -> ArtifactCheck:
        """Append a check record to the artifact history."""
        check = ArtifactCheck(
            name=name,
            question=question,
            scenario_text=scenario_text,
            trace_entry_count=len(self.trace_entries),
            metadata=dict(metadata or {}),
            answer=answer,
            success=success,
            failure_code=failure_code,
            program_path=program_path,
        )
        self.check_history.append(check)
        return check

    def to_dict(self) -> dict[str, Any]:
        """Serialize the artifact to a JSON-compatible dictionary."""
        payload = asdict(self)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StagedArtifact":
        """Deserialize a staged artifact from a dictionary."""
        execution = ArtifactExecution(**data.get("execution", {}))
        artifact = cls(
            source_text=data.get("source_text", ""),
            question=data.get("question", ""),
            scenario_text=data.get("scenario_text", ""),
            artifact_kind=data.get("artifact_kind", "check"),
            source_kind=data.get("source_kind", "policy"),
            metadata=dict(data.get("metadata", {})),
            annotations=dict(data.get("annotations", {})),
            trace_entries=[
                ArtifactTraceEntry(**entry) for entry in data.get("trace_entries", [])
            ],
            check_history=[ArtifactCheck(**check) for check in data.get("check_history", [])],
            stage_outputs=dict(data.get("stage_outputs", {})),
            context=dict(data.get("context", {})),
            context_summary=data.get("context_summary", ""),
            foundation_smt2=data.get("foundation_smt2", ""),
            program_smt2=data.get("program_smt2", ""),
            execution=execution,
            artifact_path=data.get("artifact_path"),
            parent_artifact_path=data.get("parent_artifact_path"),
            backend=data.get("backend", "staged_smt2"),
            artifact_schema_version=data.get(
                "artifact_schema_version", STAGED_ARTIFACT_SCHEMA_VERSION
            ),
            library_version=data.get("library_version", __version__),
        )
        return artifact

    def save(self, path: str | Path) -> None:
        """Persist the artifact to disk."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_path = str(destination)
        destination.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "StagedArtifact":
        """Load a staged artifact from disk."""
        source = Path(path)
        artifact = cls.from_dict(json.loads(source.read_text(encoding="utf-8")))
        artifact.artifact_path = str(source)
        return artifact

    def clone(
        self,
        *,
        artifact_kind: ArtifactKind | None = None,
        parent_artifact_path: str | None = None,
    ) -> "StagedArtifact":
        """Create a detached copy of the artifact."""
        clone = self.from_dict(self.to_dict())
        clone.artifact_path = None
        clone.parent_artifact_path = parent_artifact_path or self.artifact_path
        if artifact_kind is not None:
            clone.artifact_kind = artifact_kind
        return clone
