# API Reference

This reference documents the `2.0.0` public API.

Support status:

- `ProofOfThought()` is the default staged entrypoint
- `backend="staged_smt2"` is the explicit staged name
- `backend="smt2"` is a compatibility alias to the same staged implementation
- `backend="json"` is removed from the public API

## ProofOfThought

The main public orchestrator lives at `proofofthought.ProofOfThought`.

### Constructor

```python
def __init__(
    self,
    llm_client: Any,
    model: str = "gpt-5",
    backend: Literal["smt2", "staged_smt2"] = "staged_smt2",
    max_attempts: int = 3,
    verify_timeout: int = 10000,
    optimize_timeout: int = 100000,
    cache_dir: str | None = None,
    z3_path: str = "z3",
    postprocessors: Sequence[str | Postprocessor] | None = None,
    postprocessor_configs: dict[str, dict] | None = None,
) -> None
```

Parameters:

- `llm_client`: OpenAI-compatible client used for stage generation
- `model`: model or deployment name
- `backend`: staged default or `smt2` compatibility alias
- `max_attempts`: retry limit for end-to-end staged queries
- `verify_timeout`: Z3 timeout in milliseconds
- `optimize_timeout`: retained for advanced compatibility paths; not part of the default staged query flow
- `cache_dir`: default output directory for saved programs and artifacts
- `z3_path`: explicit Z3 binary path override
- `postprocessors`: optional postprocessor names or instances
- `postprocessor_configs`: per-postprocessor configuration

### High-level query

```python
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
) -> QueryResult
```

Behavior:

- If `text` is omitted, the question itself is used as the staged source input.
- `query()` creates a fresh `StagedArtifact`, runs stages through `query`, executes the resulting SMT-LIB with Z3, and returns a `QueryResult`.
- Retries happen at the staged query level. Users who want finer control should work directly with artifacts and individual stage APIs.

### Explicit staged workflow

Key methods for durable staged usage:

- `create_artifact(...)`
- `build_artifact(...)`
- `build_foundation(...)`
- `fork_artifact(...)`
- `add_trace_entry(...)`
- `run_check(...)`
- `run_stage(...)`
- `run_through_stage(...)`
- `execute_artifact(...)`
- `save_artifact(...)`
- `load_artifact(...)`

Typical flow:

```python
artifact = pot.build_artifact(
    text="All humans are mortal. Socrates is a human.",
    question="Is Socrates mortal?",
    through_stage="knowledge_base",
)

pot.run_stage(artifact, "scenario", rerun_downstream=True)
result = pot.execute_artifact(artifact, save_program=True)
```

## QueryResult

`QueryResult` is the product-facing execution result.

```python
@dataclass
class QueryResult:
    question: str
    answer: bool | None
    sat_count: int
    unsat_count: int
    output: str
    success: bool
    num_attempts: int
    backend: Literal["smt2", "staged_smt2"]
    program_format: Literal["smt2"] | None
    smt2_program: str | None
    program_path: str | None
    error: str | None
    failure_code: str | None
    artifact: StagedArtifact | None
    artifact_kind: Literal["foundation", "check", "audit"]
    source_kind: Literal["policy", "document", "code", "mixed"]
    check_name: str | None
```

Important fields:

- `answer`: `True` for SAT-only results, `False` for UNSAT-only results, `None` for ambiguity or failure
- `failure_code`: machine-readable failure classification
- `artifact`: the staged artifact used for execution
- `program_path`: persisted `.smt2` file path when saving is enabled

## StagedArtifact

`StagedArtifact` is the durable state object for incremental work.

```python
@dataclass
class StagedArtifact:
    source_text: str
    question: str
    scenario_text: str
    artifact_kind: Literal["foundation", "check", "audit"]
    source_kind: Literal["policy", "document", "code", "mixed"]
    metadata: dict[str, Any]
    annotations: dict[str, Any]
    trace_entries: list[ArtifactTraceEntry]
    check_history: list[ArtifactCheck]
    stage_outputs: dict[str, str]
    context: dict[str, Any]
    context_summary: str
    foundation_smt2: str
    program_smt2: str
    execution: ArtifactExecution
    artifact_path: str | None
    backend: str
    artifact_schema_version: int
    library_version: str
```

Core ideas:

- `artifact_kind` distinguishes reusable foundations, single checks, and audits
- `source_kind` distinguishes policy, document, code, or mixed foundations
- `annotations` carries contracts, invariants, or other structured constraints
- `trace_entries` carries action/observation history for audit-style checks
- `check_history` records repeated checks run against the same foundation
- `stage_outputs` stores raw outputs for `sorts`, `functions`, `constants`, `knowledge_base`, `scenario`, and `query`
- `foundation_smt2` stores the composed foundation without scenario/query layers
- `program_smt2` stores the full executable SMT-LIB program
- `execution` stores the last solver run against the artifact
- `completed_stages` reports the stages currently materialized on the artifact

Persistence helpers:

- `artifact.save(path)`
- `StagedArtifact.load(path)`
- `artifact.clear_from_stage(stage_name)`

## ArtifactExecution

```python
@dataclass
class ArtifactExecution:
    success: bool
    answer: bool | None
    sat_count: int
    unsat_count: int
    output: str
    error: str | None
    failure_code: str | None
    program_path: str | None
```

This records the latest execution result attached to a `StagedArtifact`.

## EvaluationPipeline

`proofofthought.EvaluationPipeline` handles batch evaluation.

```python
def evaluate(
    self,
    dataset: list[dict[str, Any]] | str,
    question_field: str = "question",
    answer_field: str = "answer",
    id_field: str | None = None,
    max_samples: int | None = None,
    skip_existing: bool = True,
) -> EvaluationResult
```

Behavior:

- accepts a JSON file path or in-memory records
- caches `{sample_id}_result.json` and `{sample_id}_program.smt2` artifacts in `output_dir`
- reuses the staged `ProofOfThought` instance you provide

## VerificationResult

Low-level backend execution returns:

```python
@dataclass
class VerificationResult:
    answer: bool | None
    sat_count: int
    unsat_count: int
    output: str
    success: bool
    error: str | None
    failure_code: str | None
```

## Advanced staged APIs

Power users can go deeper through `proofofthought.backends.smt2`.

Main entrypoints:

- `StagedGenerator`
- `StagedSMT2Backend`
- `ConversionContext`
- `STAGE_ORDER`

The staged generator runs the ordered phases:

```python
("sorts", "functions", "constants", "knowledge_base", "scenario", "query")
```

Use these APIs when you want direct control over prompt stages, context reconstruction, or document-grounded pipelines.

## Azure helper

`utils.azure_config.get_client_config()` returns:

```python
{
    "llm_client": AzureOpenAI(...),
    "model": str,
}
```

Required environment variables:

- `AZURE_OPENAI_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_API_VERSION`
- `AZURE_DEPLOYMENT_NAME`
