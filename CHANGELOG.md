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
- `EvaluationPipeline` scores by answer shape (see "Hardened" below):
  boolean ground truths via the boolean answer, everything else via
  normalized `answer_text`.
- Postprocessors are only supported with `smt2`/`json`; configuring them
  with the agentic backend raises `ValueError` at construction.

### Hardened (pre-release review)

A recall-biased multi-agent review of the agentic port surfaced 10 findings;
all are fixed in this release. Decisions and assumptions:

- **`ProofStatus` is first-class.** Every answer is classified as
  `proof_by_contradiction` (clean UNSAT of the negated candidate),
  `sat_witness` (a satisfying model — weaker), or `unverified`. A `finish`
  with no decisive Z3 verdict on record is rejected with instructions (up to
  `max_finish_rejections`, default 2), then accepted but tagged `unverified`
  so the answer is preserved without inflating `verified`. Within one turn,
  `z3_solve` runs before `finish` so a same-turn proof backs the finish.
- **`QueryResult` contract clarified.** `answer_text` is the canonical
  answer on every backend; `answer` is its boolean view; `success` means
  "an answer was produced" — verification strength lives exclusively in
  `verified`/`proof_status`. "sat"/"unsat" were removed from the
  boolean-coercion vocabulary (a raw verdict as an answer is ambiguous
  under the contradiction protocol).
- **Re-verification API.** `AgenticBackend.reverify(path, proof_status)`
  re-checks a saved trajectory program against the verdict that backed it,
  encapsulating negation polarity. `Backend.execute()` keeps uniform
  program-level semantics (sat→True) and now documents that this is not
  the question's answer for contradiction proofs.
- **Z3 timeouts are per-execution.** Injected as a leading
  `(set-option :timeout ...)` on a fresh context instead of the
  process-global `z3.set_param` (which raced across EvaluationPipeline
  threads and leaked into user solvers). A user `set-option` later in the
  script overrides it. `verify_timeout` now governs the agentic loop's Z3
  as well (default 10s; was a hardcoded 30s — override via
  `agentic_config`).
- **No silently ignored knobs.** `query(temperature=..., max_tokens=...)`
  reaches every backend (the single-shot generator previously dropped
  temperature too); `temperature` defaults to None = provider default
  (GPT-5-safe). When `agentic_config` is passed it is authoritative and a
  model conflict logs a warning. Postprocessors + agentic backend raise
  `ValueError` at construction instead of a buried runtime warning.
- **EvaluationPipeline scores non-boolean answers.** Boolean-like ground
  truths compare via the boolean answer; everything else compares
  normalized `answer_text` (verified MCQ answers were previously counted
  as failures, and string ground truths crashed `int()`). Binary
  precision/recall/F1 accumulate only for boolean pairs; per-sample files
  record `verified` and `proof_status` so verified-accuracy can be
  reported separately.
- **Transport robustness.** Malformed `finish` arguments now receive an
  error tool message (a dangling `tool_call_id` made strict servers reject
  the whole conversation); the `max_completion_tokens`→`max_tokens`
  fallback probe is cached per solver instance; lenient text extraction
  strips wrapper punctuation ("(A)." now recovers "A", not "A)").
- **Mechanical cleanups.** Turn handling unified in `_take_turn` (the
  final-finish follow-up no longer duplicates the loop body);
  `verdict_counts`/`z3_result_has_error` are single-sourced in the
  executor; `run_smt` takes an explicit timeout instead of a frozen
  singleton; `ast.literal_eval` replaces `eval` for bytes-repr decoding;
  default save paths are uniquified against overwrites; shared mock-LLM
  test scaffolding in `tests/mock_llm.py`.

### Unchanged

- The `smt2` and `json` backends, the JSON DSL interpreter, postprocessors,
  and the benchmark scripts are fully preserved.

## [1.0.0] - TBD
