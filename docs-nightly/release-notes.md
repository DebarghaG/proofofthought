# Nightly Release Notes

## `2.0.0` Development Line

As of April 1, 2026, the nightly channel tracks the staged-major release line. Published nightlies use versions in the form `2.0.0.devYYYYMMDDHHMM`.

## Highlights

### Staged-first public API

- `ProofOfThought()` now represents the staged product path.
- `query()` is a convenience wrapper over staged artifact construction and execution.
- `backend="smt2"` remains only as a compatibility alias to the staged implementation.
- `backend="json"` is removed from the public API.

### Durable artifact workflow

- Added `StagedArtifact` for save/load/resume behavior across sessions.
- Added explicit APIs to build artifacts, rerun stages, and execute persisted staged state.
- Query results now carry the artifact, failure code, and emitted SMT-LIB metadata.

### Low-level staged surface

- The staged SMT-LIB stack exposes ordered stage generation, context reconstruction, and direct backend execution.
- Document-grounded verification continues to use the same staged architecture rather than a separate execution path.

### Release validation

- CI builds the package, stable docs, legacy `v1.0.1` docs, and nightly docs together.
- Nightly validation includes tests, package checks, and artifact scanning before publication.

## Compatibility Notes

- Nightly is intentionally unstable and may change before the next stable cut.
- If you need the currently available legacy line, use the `1.0.1` docs at `/v1.0.1/`.
- The package still requires Python 3.13 and a working `z3` executable for staged verification flows.
