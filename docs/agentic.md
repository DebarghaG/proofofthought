# Agentic Reasoning

**The agentic SMT-LIB scratchpad is the paradigm ProofOfThought is moving towards going forward.** It is the default backend as of v2.0.0.

## Why agentic?

The classic ProofOfThought flow generates one whole program, executes it, and — on failure — regenerates the whole program with the error pasted back. That works, but it treats the solver as a batch compiler.

The agentic paradigm instead treats Z3 as an **interactive scratchpad**. The model:

1. Thinks briefly about the problem.
2. Calls the `z3_solve` tool with a complete SMT-LIB 2.6 program.
3. Reads Z3's verdict — `sat`, `unsat`, `unknown`, or a syntax/type error.
4. Repairs or strengthens its encoding and calls `z3_solve` again, as many times as needed.
5. Once Z3 confirms the answer, calls the `finish` tool with the verified answer.

Each Z3 verdict lands back in the conversation, so the model accumulates an audit trail of formal experiments rather than restarting from scratch on every error. The trajectory is an interpretability artifact: every answer ships with the exact SMT programs tried and the verdicts Z3 returned.

## Proof by contradiction, as a first-class concept

The canonical way the loop verifies an answer is **proof by contradiction**: the model asserts the *negation* of its candidate answer and asks Z3 for `(check-sat)`. A clean `unsat` means no model of the premises can violate the candidate — the answer is proven.

Every answer therefore carries a `ProofStatus` describing how the trajectory backs it:

| status | meaning | strength |
|---|---|---|
| `proof_by_contradiction` | the last decisive verdict was a clean `unsat` of the negated candidate | a proof |
| `sat_witness` | the last decisive verdict was a clean `sat` — Z3 found a model consistent with the answer | a witness: right for existence questions, weaker everywhere else |
| `unverified` | the answer was recorded without a usable verdict (rejected-finish budget ran out, or lenient text extraction) | an ordinary LLM guess |

```python
from z3adapter.agentic import ProofStatus

result = pot.query("...")
if result.proof_status == ProofStatus.PROOF_BY_CONTRADICTION:
    ...  # formally proven
```

**`finish` is not taken at face value.** A finish call with no decisive Z3 verdict on record is *rejected* — the model receives a tool message telling it to verify first — up to `max_finish_rejections` times. After that (or when no turns remain) the answer is accepted but honestly tagged `unverified`, so the answer is never lost *and* `verified=True` always means "backed by a decisive verdict", never "the model said so". Within a single turn, `z3_solve` calls run before `finish`, so a same-turn proof backs the finish.

## Quick start

```python
from openai import OpenAI
from z3adapter.reasoning import ProofOfThought

client = OpenAI()
pot = ProofOfThought(llm_client=client, model="gpt-5")  # agentic is the default

result = pot.query("Is there an integer that is both greater than 5 and less than 3?")
print(result.answer_text)   # "No"  — canonical answer, any shape (Yes/No, MCQ letter, value)
print(result.answer)        # False — boolean view; None for non-boolean answers
print(result.verified)      # True  — backed by a decisive Z3 verdict
print(result.proof_status)  # "proof_by_contradiction"
print(result.iterations)    # tool-loop turns taken
for step in result.smt_history:
    print(step["smt_code"])                  # every SMT program tried
    print(step["z3_output"]["sat_result"])   # and Z3's verdict for it
```

The `QueryResult` contract, uniform across backends:

- **`answer_text`** — the canonical answer; always set when an answer was produced.
- **`answer`** — boolean view of `answer_text`; `None` for non-boolean answers (check `success` to distinguish "non-boolean" from "no answer").
- **`success`** — an answer was produced. Verification strength lives in `verified` / `proof_status`, never in `success`.

Any OpenAI-compatible client works: `OpenAI`, `AzureOpenAI`, or a local vLLM/sglang endpoint wrapped in the OpenAI SDK:

```python
client = OpenAI(base_url="http://localhost:8000/v1", api_key="none")
pot = ProofOfThought(llm_client=client, model="Qwen/Qwen3.5-9B")
```

## Re-verifying a trajectory

The final program of a trajectory is a standard `.smt2` file — save it and re-check the proof later, in CI, or on another machine:

```python
result = pot.query("...", save_program=True, program_path="proof.smt2")

backend = pot.backend  # AgenticBackend
assert backend.reverify("proof.smt2", result.proof_status)
```

`reverify()` encapsulates the negation polarity: a `proof_by_contradiction` artifact must still yield `unsat`, a `sat_witness` must still yield `sat`, and an `unverified` answer has no proof to re-establish (always `False`). Note that the lower-level `AgenticBackend.execute()` — like every `Backend` — reports *program-level* satisfiability (`sat→True`, `unsat→False`), which for a contradiction proof is **not** the question's answer; use `reverify()` and never invert booleans by hand.

## Robustness features

Ported from the NL2SMTLIB-Benchmark evaluation harness, where they were tuned over tens of thousands of agent trajectories:

- **In-process Z3** — programs run via the Z3 Python API (`Z3_eval_smtlib2_string`), so no `z3` CLI binary is required and the full command surface (`get-model`, `push`/`pop`, ...) is supported.
- **Per-execution timeouts** — the timeout is injected as a per-script `(set-option :timeout ...)` on a fresh context, never via the process-global `z3.set_param`, so concurrent evaluations can't race on each other's timeouts and nothing leaks into your own Z3 solvers. A `set-option` inside your script overrides it.
- **Verdict classification** — `(error ...)` *before* a verdict line invalidates it (Z3's default-context `sat` after failed declarations is not a result); `(error "model is not available")` *after* a clean `unsat` does not.
- **Finish discipline** — see [Proof by contradiction](#proof-by-contradiction-as-a-first-class-concept): premature finishes are rejected, accepted answers are classified, and every tool call (including malformed ones) receives a tool response so strict servers never see a dangling `tool_call_id`.
- **Tool-result truncation** — long `(get-model)` dumps are HEAD+TAIL truncated so accumulated history doesn't blow the context window.
- **Nudge policy** — when a turn produces no tool call, the loop pushes the model with a nudge derived from the last Z3 verdict (fix errors / convert SAT into a proof / finish after UNSAT). The nudge budget resets on each successful tool call.
- **Final-finish follow-up** — if the last allowed iteration produces a clean UNSAT, the loop grants one bounded follow-up so the proof isn't wasted for lack of a `finish` turn.
- **Textual tool-call recovery** — models served behind vLLM/sglang often emit textual tool calls (hermes JSON, qwen XML, broken hybrids, or raw SMT-LIB) that the server's parser misses; `z3adapter.agentic.parsing` recovers them. With well-behaved API models this is a no-op.

## Tuning the loop

```python
from z3adapter.agentic import AgenticConfig
from z3adapter.reasoning import ProofOfThought

config = AgenticConfig(
    model="gpt-5",
    max_iterations=10,          # tool-loop turns
    max_consecutive_nudges=2,   # pushes after a no-tool-call turn
    max_finish_rejections=2,    # premature finishes rejected before accepting as unverified
    z3_timeout_ms=30000,
    temperature=None,           # None = don't send (required for GPT-5)
    lenient_extraction=False,   # opt-in: recover answers from text on no_finish
)
pot = ProofOfThought(llm_client=client, agentic_config=config)
```

When `agentic_config` is omitted, `ProofOfThought`'s own arguments configure the loop: `model`, `max_iterations`, and `verify_timeout` (which governs the in-process Z3 timeout, default 10s). When `agentic_config` **is** provided it is authoritative — set the model on it.

Per-query overrides are honored on every backend:

```python
result = pot.query(question, temperature=0.7, max_tokens=4096)
```

`temperature=None` (the default) sends nothing and uses the provider default — required for models like GPT-5 that reject non-default temperatures.

Or use the solver directly, without the high-level API:

```python
from z3adapter.agentic import AgenticSolver, AgenticConfig

solver = AgenticSolver(client, AgenticConfig(model="gpt-5"))
result = solver.solve(
    "Which option is correct?",
    answer_format="Answer choices:\n  A) ...\n  B) ...",
)
print(result.answer, result.proof_status, result.extraction_method)
```

`AgenticResult` carries the full trajectory: `messages` (transcript including any reasoning channel), `smt_history`, `token_usage` per call, `proof_status`, and `extraction_method` (`tool_call_finish`, `tool_call_finish_unverified`, `text_pattern_extracted`, or `none`).

## Batch evaluation

`EvaluationPipeline` scores answers by shape: boolean-like ground truths compare via the boolean answer; everything else (multiple choice, free-form) compares `answer_text` under whitespace/case normalization. Binary metrics (precision/recall/F1) accumulate only for boolean pairs. Each per-sample result file records `answer_text`, `verified`, and `proof_status`, so you can report *verified accuracy* separately from raw accuracy:

```python
evaluator = EvaluationPipeline(proof_of_thought=pot, output_dir="results/")
result = evaluator.evaluate(dataset="data/strategyQA_train.json", max_samples=100)
print(result.metrics.accuracy)
```

## Relationship to the classic backends

The `smt2` and `json` backends remain fully supported — pass `backend="smt2"` or `backend="json"` to get the single-shot pre-2.0 behavior. Postprocessors (Self-Refine, Self-Consistency, ...) apply only to the single-shot backends; configuring them together with the agentic backend raises `ValueError` at construction rather than silently doing nothing.
