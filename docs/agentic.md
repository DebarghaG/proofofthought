# Agentic Reasoning

**The agentic SMT-LIB scratchpad is the paradigm ProofOfThought is moving towards going forward.** It is the default backend as of v2.0.0.

## Why agentic?

The classic ProofOfThought flow generates one whole program, executes it, and — on failure — regenerates the whole program with the error pasted back. That works, but it treats the solver as a batch compiler.

The agentic paradigm instead treats Z3 as an **interactive scratchpad**. The model:

1. Thinks briefly about the problem.
2. Calls the `z3_solve` tool with a complete SMT-LIB 2.6 program.
3. Reads Z3's verdict — `sat`, `unsat`, `unknown`, or a syntax/type error.
4. Repairs or strengthens its encoding and calls `z3_solve` again, as many times as needed.
5. Once Z3 confirms the answer (canonically: a clean **UNSAT of the negated candidate answer**, i.e. a proof), calls the `finish` tool with the verified answer.

Each Z3 verdict lands back in the conversation, so the model accumulates an audit trail of formal experiments rather than restarting from scratch on every error. In our evaluation harness this loop substantially outperforms single-shot generation on multi-step reasoning benchmarks, and every answer comes with a machine-checkable trajectory.

## Quick start

```python
from openai import OpenAI
from z3adapter.reasoning import ProofOfThought

client = OpenAI()
pot = ProofOfThought(llm_client=client, model="gpt-5")  # agentic is the default

result = pot.query("Is there an integer that is both greater than 5 and less than 3?")
print(result.answer)        # False (boolean view, for yes/no questions)
print(result.answer_text)   # "No"  (raw verified answer from finish())
print(result.verified)      # True  (the model explicitly finished)
print(result.iterations)    # how many tool-loop turns it took
for step in result.smt_history:
    print(step["smt_code"])               # every SMT program tried
    print(step["z3_output"]["sat_result"])  # and Z3's verdict for it
```

Any OpenAI-compatible client works: `OpenAI`, `AzureOpenAI`, or a local vLLM/sglang endpoint wrapped in the OpenAI SDK:

```python
client = OpenAI(base_url="http://localhost:8000/v1", api_key="none")
pot = ProofOfThought(llm_client=client, model="Qwen/Qwen3.5-9B")
```

## The verification protocol

The system prompt enforces a proof discipline rather than satisfiability checking:

- **True/False questions** — assert the *negation* of the expected answer; `unsat` proves it.
- **Multiple choice** — encode the constraints, assert the negation of the candidate, show `unsat`.
- A bare `sat` is *not* accepted as a proof; the loop nudges the model to convert it into an UNSAT-of-the-negation argument before finishing.

## Robustness features

Ported from the NL2SMTLIB-Benchmark evaluation harness, where they were tuned over tens of thousands of agent trajectories:

- **In-process Z3** — programs run via the Z3 Python API (`Z3_eval_smtlib2_string`), so no `z3` CLI binary is required and the full command surface (`get-model`, `push`/`pop`, ...) is supported.
- **Verdict classification** — `(error ...)` *before* a verdict line invalidates it (Z3's default-context `sat` after failed declarations is not a result); `(error "model is not available")` *after* a clean `unsat` does not.
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
    z3_timeout_ms=30000,
    temperature=None,           # None = don't send (required for GPT-5)
    lenient_extraction=False,   # opt-in: recover answers from text on no_finish
)
pot = ProofOfThought(llm_client=client, agentic_config=config)
```

Or use the solver directly, without the high-level API:

```python
from z3adapter.agentic import AgenticSolver, AgenticConfig

solver = AgenticSolver(client, AgenticConfig(model="gpt-5"))
result = solver.solve(
    "Which option is correct?",
    answer_format="Answer choices:\n  A) ...\n  B) ...",
)
print(result.answer, result.extraction_method)
```

`AgenticResult` carries the full trajectory: `messages` (transcript including any reasoning channel), `smt_history`, `token_usage` per call, and `extraction_method` (`tool_call_finish`, `text_pattern_extracted`, or `none`).

## Relationship to the classic backends

The `smt2` and `json` backends remain fully supported — pass `backend="smt2"` or `backend="json"` to get the exact pre-2.0 behavior, including postprocessors (Self-Refine, Self-Consistency, etc., which currently apply only to the single-shot backends).

The final SMT program of an agentic trajectory is a standard `.smt2` file: `pot.query(..., save_program=True, program_path="proof.smt2")` saves it, and `AgenticBackend.execute("proof.smt2")` (or the classic `SMT2Backend`) can independently re-verify it.
