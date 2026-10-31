# Trajectory Guardrails

`z3adapter.guardrails` turns the agentic SMT-LIB backend into a **formal guardrail for tool-calling agents**: it verifies that an agent's tool-call trajectory — every call individually *and* the composition across calls — complies with a domain policy, and it can gate a proposed tool call online before it executes. It works out of the box on the [TauBench](https://github.com/sierra-research/tau-bench) and [tau2-bench (τ²)](https://github.com/sierra-research/tau2-bench) trajectory formats.

## How it works

Everything reuses the existing agentic machinery — the guardrail is two `AgenticSolver` runs with different system prompts:

1. **Autoformalization** (once per policy). `formalize_policy()` points the standard agentic loop at the natural-language rulebook (a tau-bench `wiki.md` or tau2 `policy.md`) and asks it to build a *step-indexed* SMT-LIB theory: an enumerated datatype of the domain's tools, uninterpreted functions over step indices (`tool_at`, `user_authenticated_by`, `explicit_confirmation_before`, order status observed at call time, ...), one `rule_k_violated(i)` predicate per enforceable rule, and a top-level `any_violation`. The loop iterates `z3_solve` until Z3 accepts the theory as **consistent (`sat`)**; the last Z3-validated program becomes the formal artifact, persisted with `policy.save()`.

2. **Audit** (per trajectory or per proposed call). `TrajectoryGuardrail` runs the agentic loop with the theory and a rendered transcript of the trajectory. The verifier asserts the theory, the concrete facts of each step (which tool ran, what state its result revealed, which confirmations are on the record), and then `(assert any_violation)`:

   | Z3 verdict | meaning | verdict |
   |---|---|---|
   | `unsat` | no step — alone or in composition — can violate any rule | `SAFE`, `proof_status = proof_by_contradiction` |
   | `sat` | Z3 found a concrete model of a violated rule at a specific step | `VIOLATION`, `proof_status = sat_witness` |
   | anything else | no decisive verdict | `INCONCLUSIVE`, `allowed = None` |

Because the theory quantifies over steps and the whole tool-call sequence is asserted at once, **compositional rules are part of the same satisfiability question as per-call preconditions**: authenticate-before-account-actions, explicit-confirmation-before-every-write, at-most-once tools (e.g. tau-bench's "exchange or modify order tools can only be called once"), and preconditions established or destroyed by earlier calls (a second exchange is invalid *because* the first one changed the order status).

The finish discipline carries over unchanged, plus one extra check: the verifier's finish answer is cross-checked against its own proof status (`SAFE`⇔`unsat`, `VIOLATION`⇔`sat`); a mismatched or unverified verdict is downgraded to `INCONCLUSIVE` rather than trusted, and the caller decides whether to fail open or closed.

## Quick start

```python
from openai import OpenAI
from z3adapter.guardrails import (
    TrajectoryGuardrail, formalize_policy, taubench_policy,
    load_taubench_trajectories,
)

client = OpenAI()

# 1. Formalize the domain policy once and cache it.
policy = taubench_policy("retail", "external/tau-bench")
policy = formalize_policy(policy, client)
policy.save("retail_policy.json")            # later: Policy.load(...)

# 2. Audit recorded benchmark trajectories.
guard = TrajectoryGuardrail(client, policy)
trajectories = load_taubench_trajectories(
    "external/tau-bench/historical_trajectories/gpt-4o-retail.json"
)
verdict = guard.check_trajectory(trajectories[0])
print(verdict.status)        # "safe" | "violation" | "inconclusive"
print(verdict.allowed)       # True | False | None
print(verdict.proof_status)  # "proof_by_contradiction" for safe trajectories
print(verdict.explanation)   # names the violated rule / step for violations
```

tau2-bench results files (`{timestamp, info, tasks, simulations}`) load the same way with `load_tau2_trajectories(...)` and `tau2_policy("retail" | "airline" | "telecom", repo_root)`.

## Online gating of tool calls

`check_tool_call` audits a *proposed* call as the next step on top of the conversation so far — before it executes. Violations it would commit in composition with earlier calls are caught, not just bad arguments:

```python
verdict = guard.check_tool_call(
    messages,                          # the OpenAI message list so far
    "exchange_delivered_order_items",  # what the agent wants to call
    {"order_id": "#W2378156", "item_ids": ["3"], ...},
)
if verdict.allowed is False:
    ...  # block the call; verdict.explanation names the rule it would break
elif verdict.allowed is None:
    ...  # inconclusive: fail open or closed per your risk posture
```

## Re-checking audits

Every verdict carries `smt_program` — the final SMT program of the audit, a standard `.smt2` artifact that re-yields the verdict. It re-checks under the library's standard contract, independently of any LLM:

```python
with open("audit.smt2", "w") as f:
    f.write(verdict.smt_program)
assert guard.backend.reverify("audit.smt2", verdict.proof_status)
```

`verify_theory(policy)` likewise re-checks that a saved policy theory is still consistent (`sat`) — a theory drifted to `unsat` would prove any verdict vacuously.

## Honest semantics — what is and isn't proven

The UNSAT/SAT verdict is a genuine machine-checked proof **relative to the facts the verifier asserted**. Extracting those facts from the transcript (did the user's "yes" confirm *this specific* action?) is LLM judgment, same as autoformalization everywhere. The guardrail narrows that trust surface: the verifier is instructed to assert *absence* of confirmations it cannot see (defaulting to violation rather than compliance), polarity mismatches are rejected mechanically, and both the theory and every audit are persisted as re-checkable SMT-LIB. Treat `INCONCLUSIVE` as its own outcome — it is deliberately never coerced to safe.

## End-to-end example

`examples/guardrail_taubench.py` runs the full pipeline (formalize → cache → batch audit → online gate) against the trajectory fixtures checked into either benchmark repo:

```bash
git clone --depth 1 https://github.com/sierra-research/tau-bench external/tau-bench
git clone --depth 1 https://github.com/sierra-research/tau2-bench external/tau2-bench
python examples/guardrail_taubench.py --benchmark taubench --domain retail --max-trajectories 3
python examples/guardrail_taubench.py --benchmark tau2 --domain airline
```

Observed behavior with Claude Sonnet 4.5 on tau-bench retail: real recorded trajectories (both reward-1 and reward-0 runs whose failures were answer-quality, not policy breaches) prove `SAFE` by contradiction in ~2 verifier iterations; an unauthenticated + unconfirmed `cancel_pending_order` is flagged `VIOLATION` with the exact rules named; a second `exchange_delivered_order_items` call — where each call is individually well-formed — is flagged as a compositional violation both offline and via the online gate, and every audit artifact re-verifies with `AgenticBackend.reverify`.
