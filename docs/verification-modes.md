# Verification Modes

ProofOfThought `2.0.0` uses one staged model for all supported verification workflows:

**foundation + scenario/trace + checks + execution**

That means policy guardrails, agent audits, and code verification all use the same API surface. You do not need different product families for each workload.

## Shared Mental Model

1. Build or load a reusable `StagedArtifact` foundation.
2. Attach a scenario, proposed action, or trace.
3. Run one or more checks against that state.
4. Execute the composed SMT-LIB with Z3 and inspect the result.

Use `source_kind` to describe what the foundation represents:

- `policy`
- `document`
- `code`
- `mixed`

Use `artifact_kind` to describe how you are using it:

- `foundation`
- `check`
- `audit`

## Agent Guardrails

Pre-action guardrails use a reusable policy or system-behavior foundation plus a proposed action scenario.

```python
from proofofthought import ProofOfThought

pot = ProofOfThought(llm_client=client)

foundation = pot.build_foundation(
    text="Transfers above 10000 USD require dual approval.",
    source_kind="policy",
)

result = pot.run_check(
    foundation,
    question="May the agent call submit_transfer?",
    scenario_text="The agent proposes submit_transfer(amount=25000, approvals=1).",
    check_name="transfer_guardrail",
)
```

This is the default shape for tool-call guardrails:

- foundation: policy, tool contract, system rules
- scenario: proposed tool call or action
- check: "is this allowed?" or "does this violate an invariant?"

## Agent Trace Auditing

Post-hoc auditing uses the same foundation, but adds trace entries over time. Once trace entries exist, the artifact naturally becomes an `audit`.

```python
audit = pot.fork_artifact(
    foundation,
    artifact_kind="audit",
    question="Did the executed trace violate policy?",
)

pot.add_trace_entry(audit, "balance=20", entry_type="observation")
pot.add_trace_entry(
    audit,
    "withdraw(account_id='acct_1', amount=50)",
    entry_type="action",
)

result = pot.run_check(
    audit,
    question="Does the trace violate the balance invariant?",
    check_name="trace_audit",
)
```

Use this mode for:

- trajectory review
- invariant checks over multi-step tool use
- incident analysis and replay
- agent evaluation harnesses

`trace_entries`, `check_history`, `failure_code`, and persisted artifact versions make the results easier to inspect and reuse.

## Code Verification

Code verification uses the same staged workflow, but the foundation source is code plus explicit annotations such as contracts and invariants.

```python
code_foundation = pot.build_foundation(
    text="""
def transfer(balance: int, amount: int) -> int:
    return balance - amount
""",
    source_kind="code",
    annotations={
        "preconditions": ["amount >= 0", "amount <= balance"],
        "postconditions": ["result == balance - amount"],
        "invariants": ["balance >= 0"],
    },
)

result = pot.run_check(
    code_foundation,
    question="Can transfer produce a negative balance?",
    scenario_text="Assume balance = 20 and amount = 50.",
    check_name="transfer_contract_check",
)
```

This mode is aimed at:

- contract checking
- invariant validation
- code-oriented agent guardrails
- auditing whether an agent-made code claim is consistent with declared semantics

## Which API To Use

- Use `query()` when you want the shortest one-shot path.
- Use `build_foundation()` plus `run_check()` when you want reusable foundations.
- Use `fork_artifact()` when you want many checks against one foundation.
- Use `add_trace_entry()` when you want trajectory auditing.
- Use `annotations` with `source_kind="code"` when you want contract-style code verification.
