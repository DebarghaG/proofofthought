# Backends

`2.0.0` has one real execution architecture: the staged SMT-LIB pipeline.

## Default staged path

`ProofOfThought()` already uses the staged backend.

Use the explicit `backend="staged_smt2"` name when you want to be explicit in configs, tests, or migration code.

Use it when you want:

- explicit staged artifacts
- resumable stage execution over time
- direct access to the staged SMT-LIB internals
- the primary product path for the major release

## `smt2`

`backend="smt2"` remains as a compatibility alias.

It routes to the same staged implementation as `staged_smt2`. It exists to reduce migration pain for users coming from the prior release line.

## Removed: `json`

`backend="json"` is no longer part of the public API in `2.0.0`.

If you still need the JSON/Z3-DSL path, use the legacy `1.0.1` release and docs.

## Choosing A Backend

| Backend | Status | What it means |
|---------|--------|---------------|
| default / `staged_smt2` | Canonical | Staged backend |
| `smt2` | Compatibility alias | Same staged implementation, older name |
| `json` | Removed | Use `1.0.1` docs if you still need it |

## Runtime Behavior

### Saved Programs

`ProofOfThought.query(..., save_program=True)` saves the composed staged SMT-LIB program as `.smt2`.

`QueryResult` also exposes:

- `program_format`
- `program_path`
- `failure_code`
- `artifact`

### Z3 Resolution

For SMT-LIB backends, the library resolves `z3` in this order:

1. `PATH`
2. the active Python environment's `bin/` or `Scripts/` directory
3. common repo-local virtual environments such as `venv/` and `.venv/`

You can still override this explicitly with `z3_path="/custom/path/to/z3"`.

## Migrating Off JSON

If you are migrating from the legacy line:

1. Switch to `ProofOfThought()` or `ProofOfThought(..., backend="staged_smt2")`.
2. Treat `query()` as a staged convenience path rather than a separate architecture.
3. Use `StagedArtifact` for any workflow that needs persistence, inspection, or iterative refinement over time.
4. Refer to `/v1.0.1/` if you need the older behavior during migration.
