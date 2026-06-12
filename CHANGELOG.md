# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-06-12

### The agentic release

ProofOfThought is moving to an **agentic paradigm** going forward: the model
iteratively interacts with an SMT-LIB scratchpad by calling a `z3_solve` tool,
reading Z3's verdict, repairing its encoding, and terminating with an explicit
`finish` tool call once the answer is formally verified. The loop was developed
and battle-tested in the NL2SMTLIB-Benchmark evaluation harness.

### Added

- `z3adapter.agentic` package:
  - `AgenticSolver` / `AgenticConfig` / `AgenticResult` — the iterative
    `z3_solve` ⇄ `finish` tool loop with verdict-aware nudges, tool-result
    HEAD+TAIL truncation, a bounded final-finish follow-up after a clean
    UNSAT, and optional lenient answer extraction.
  - `Z3Executor` — in-process SMT-LIB execution via the Z3 Python API
    (`Z3_eval_smtlib2_string`); no `z3` CLI binary required. Hardened verdict
    classification (`z3_result_is_useful`): errors *before* a verdict line
    invalidate it, post-verdict `(error ...)` noise after a clean `unsat`
    does not.
  - `parsing` — recovery of textual tool calls (hermes JSON, qwen XML,
    broken hybrids, bare SMT-LIB) that OpenAI-compatible servers fail to
    parse into structured `tool_calls`.
- `AgenticBackend` — `Backend` implementation that re-executes saved `.smt2`
  programs in-process, keeping `EvaluationPipeline` and program saving
  uniform across backends.
- `QueryResult` gained `answer_text`, `smt_history`, `iterations`, and
  `verified` fields (defaulted, fully backward compatible).
- `ProofOfThought` gained `max_iterations` and `agentic_config` parameters.
- Documentation: `docs/agentic.md`; example: `examples/agentic_usage.py`.
- 37 new unit/integration tests covering the executor, tool-call parsing,
  the solve loop, and the high-level API.

### Changed

- **Breaking:** the default backend is now `"agentic"`. Pass
  `backend="smt2"` (or `"json"`) to `ProofOfThought` to retain the exact
  pre-2.0 single-shot behavior.
- `EvaluationPipeline` records `answer_text` and skips binary-metric
  accumulation for verified non-boolean answers (e.g. multiple choice)
  instead of crashing.
- Postprocessors are skipped with a warning under the agentic backend; they
  continue to work with `smt2`/`json`.

### Unchanged

- The `smt2` and `json` backends, the JSON DSL interpreter, postprocessors,
  and the benchmark scripts are fully preserved.

## [1.0.0] - TBD
