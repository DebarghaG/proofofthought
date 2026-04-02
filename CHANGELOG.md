# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Documentation

- Added branch-level nightly release notes for the staged pipeline work

## [2.0.0] - TBD

### Changed

- Made the staged SMT-LIB pipeline the default product architecture
- Made `ProofOfThought.query()` a convenience wrapper over staged artifact construction and execution
- Added `StagedArtifact` as the durable save/load/resume state model
- Kept `backend="smt2"` only as a compatibility alias to the staged implementation
- Removed `backend="json"` from the public API
- Expanded runtime support to Python `3.10+`
- Made `proofofthought` the canonical import root for the major release

### Added

- Stage-oriented artifact APIs for create/build/load/save/rerun workflows
- Machine-readable `failure_code` and persisted program/artifact metadata on query results
- Versioned documentation builds for the current major line, nightly line, and legacy `v1.0.1`
- Generalized staged artifact modes for reusable foundations, checks, audits, and code contracts
- Release packaging checks that fail if removed JSON-era modules leak into built artifacts

### Documentation

- Rewrote the public docs around staged usage, artifact persistence, agent guardrails, code verification, and the `1.0.1` legacy line

## [1.0.1.dev202604011558] - 2026-04-01

### Added

- Staged SMT2 backend support exposed through `ProofOfThought(..., backend="staged_smt2")`
- Multi-stage SMT2 generation components, including staged prompts, IR, parser, emitter, and backend execution support
- Document-grounded staged verification APIs: `DocumentVerificationPipeline`, `build_document_model`, `verify_qa_pairs`, `evaluate_dataset`, and `load_question_selector`
- NL-SMT-Bench document verification example and end-to-end integration coverage
- Manual GitHub Actions workflow for publishing nightly prereleases to PyPI
- Artifact safety scan that blocks uploads if the wheel or source distribution contains obvious secret material
- Separate nightly documentation site published under `/nightly/`

### Changed

- Examples and docs now cover staged autoformalization and document-grounded verification workflows
- Package version metadata now comes from `z3adapter._version`
- Nightly builds use prerelease versions in the form `BASE.devYYYYMMDDHHMM`

### Documentation

- Added nightly install instructions, release-channel guidance, and branch-specific release notes

## [1.0.1] - TBD

### Changed

- Current stable base version
