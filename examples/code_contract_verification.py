#!/usr/bin/env python3
"""Example: staged code verification with contracts and invariants."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from proofofthought import ProofOfThought

project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError(
        "OPENAI_API_KEY is not set. Please set it in your .env file or environment variables."
    )

client = OpenAI(api_key=api_key)
pot = ProofOfThought(llm_client=client, model="gpt-4o")

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
    artifact_path=str(project_root / "output" / "transfer.foundation.json"),
)

result = pot.run_check(
    code_foundation,
    question="Can transfer return a negative balance?",
    scenario_text="Assume balance = 20 and amount = 50.",
    check_name="transfer_contract_check",
    save_program=True,
    program_path=str(project_root / "output" / "transfer_contract_check.smt2"),
    save_artifact=True,
)

print("\n" + "=" * 80)
print("CODE VERIFICATION RESULT")
print("=" * 80)
print(f"Answer: {result.answer}")
print(f"Success: {result.success}")
print(f"Failure code: {result.failure_code}")
print(f"Program path: {result.program_path}")
print(f"Artifact kind: {result.artifact_kind}")
print(f"Source kind: {result.source_kind}")
print(f"Check name: {result.check_name}")
