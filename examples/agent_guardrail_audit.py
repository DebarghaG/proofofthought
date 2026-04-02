#!/usr/bin/env python3
"""Example: staged agent guardrails and trajectory auditing."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from proofofthought import ProofOfThought


project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY is not set. Add it to .env or the environment.")

client = OpenAI(api_key=api_key)
pot = ProofOfThought(llm_client=client, model="gpt-4o")

foundation = pot.build_foundation(
    text="""
Tool-use policy:
- The payments agent may not initiate a transfer larger than the available balance.
- Transfers above 10,000 USD require dual approval.
- Refunds require a matching customer support ticket.
""",
    source_kind="policy",
    metadata={"policy_name": "payments_guardrails"},
)

guardrail_result = pot.run_check(
    foundation,
    question="May the agent call submit_transfer?",
    scenario_text=(
        "The agent wants to submit_transfer(amount=25000, approvals=1, available_balance=40000)."
    ),
    check_name="pre_action_guardrail",
)

print("Pre-action guardrail answer:", guardrail_result.answer)
print("Failure code:", guardrail_result.failure_code)

audit = pot.fork_artifact(
    foundation,
    artifact_kind="audit",
    question="Did the executed agent trace violate the payments policy?",
    scenario_text="Audit the following observed trace against the policy foundation.",
)
pot.add_trace_entry(
    audit,
    "Agent observed available_balance=20 and planned withdraw(amount=50).",
    entry_type="observation",
)
pot.add_trace_entry(
    audit,
    "Agent executed withdraw(account_id='acct_1', amount=50).",
    entry_type="action",
)
pot.add_trace_entry(
    audit,
    "Tool result returned status='completed'.",
    entry_type="tool_result",
)

audit_result = pot.run_check(
    audit,
    question="Does the trace show an invariant violation?",
    check_name="post_hoc_audit",
    save_artifact=True,
    artifact_path="output/agent_audit.artifact.json",
)

print("Audit answer:", audit_result.answer)
print("Artifact kind:", audit_result.artifact_kind)
print("Recorded checks:", len(audit_result.artifact.check_history) if audit_result.artifact else 0)
