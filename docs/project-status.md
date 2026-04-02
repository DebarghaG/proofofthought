# Project Status

ProofOfThought `2.0.0` is now positioned as a **staged-SMT** library.

## Stability Levels

### Stable

- `ProofOfThought()` and `ProofOfThought(..., backend="staged_smt2")`
- `ProofOfThought(..., backend="smt2")` as a compatibility alias to the staged implementation
- `StagedArtifact` persistence and stage rerun APIs
- Reusable foundation, guardrail, audit, and code-verification workflows built on `StagedArtifact`
- `EvaluationPipeline`
- Core install and packaging flow
- Primary examples and documentation

This is the path the project intends to support long term for external users.

### Advanced

- `DocumentVerificationPipeline`
- `StagedGenerator` and the lower-level APIs in `proofofthought.backends.smt2`

These APIs are actively supported, but they are more specialized than the high-level staged facade.

### Legacy

- `1.0.1` documentation and the pre-major release behavior
- Removed JSON backend / JSON-Z3 DSL product surface

Use `/v1.0.1/` if you need the currently available legacy release line.

## Operational Notes

- The library resolves `z3` from `PATH` first, then falls back to the active Python environment and common repo-local virtual environments such as `venv/` and `.venv/`.
- Query results now expose `failure_code`, `program_format`, `program_path`, and the staged artifact used for execution.
- The top-level `query()` path is implemented as staged orchestration rather than as a separate architecture.
