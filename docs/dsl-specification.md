# DSL Specification

The JSON DSL is legacy-only in `2.0.0`.

If you need the old JSON/Z3-DSL product surface, use the archived `1.0.1` line and docs at `/v1.0.1/`.

## Status

- `backend="json"` is removed from the public API
- the staged SMT-LIB pipeline is the only supported execution architecture in `2.0.0`
- this page exists only to explain what the legacy DSL was and how to migrate away from it

## What The Legacy DSL Covered

The old DSL serialized solver programs as JSON structures that described:

- sorts
- functions and predicates
- constants
- knowledge-base assertions
- rules
- verifications
- optional optimization directives

That model was useful for early experimentation, but it required a custom interpretation layer and a larger compatibility and security surface than the staged SMT-LIB flow.

## Why It Is No Longer The Product Path

The staged `2.0.0` line replaces the JSON DSL with:

- explicit stage outputs
- resumable `StagedArtifact` persistence
- direct SMT-LIB program emission
- Z3 execution without a public JSON program format

This gives the library one durable execution format while still exposing low-level staged APIs for users who want to inspect or control the formalization process.

## Migration Guidance

If you are migrating from the legacy JSON line:

1. Replace `ProofOfThought(..., backend="json")` with `ProofOfThought()`.
2. Treat `query()` as a staged convenience wrapper over the artifact workflow.
3. Save and reload `StagedArtifact` objects instead of JSON programs.
4. Use `/v1.0.1/` if you need the old release line during migration.

## Need The Full Legacy Spec?

Use the `1.0.1` documentation set and release line. This `2.0.0` site does not preserve the full JSON DSL contract because it is no longer part of the supported public product surface.
