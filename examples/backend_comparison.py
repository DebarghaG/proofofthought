#!/usr/bin/env python3
"""
Compare the high-level one-shot path with explicit staged control.

This example shows that the simple API is a convenience wrapper over the same
staged artifact workflow that advanced users can drive directly.
"""

import logging

from azure_config import get_client_config

from proofofthought import ProofOfThought

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Get Azure GPT-5 configuration
config = get_client_config()

# Test question
question = "Can fish breathe underwater?"

print("=" * 80)
print("ONE-SHOT VS EXPLICIT STAGED WORKFLOW")
print("=" * 80)

# Test with high-level one-shot query first
print("\n[1/2] One-Shot Query")
print("-" * 80)
pot = ProofOfThought(llm_client=config["llm_client"], model=config["model"])

result_direct = pot.query(question, save_program=True, save_artifact=True)
print(f"Question: {question}")
print(f"Answer: {result_direct.answer}")
print(f"Success: {result_direct.success}")
print(f"Attempts: {result_direct.num_attempts}")
print(f"SAT count: {result_direct.sat_count}")
print(f"UNSAT count: {result_direct.unsat_count}")
print(f"Completed stages: {result_direct.artifact.completed_stages if result_direct.artifact else []}")

if not result_direct.success:
    print(f"Error: {result_direct.error}")
    raise SystemExit(1)

# Test with explicit staged workflow
print("\n[2/2] Explicit Staged Workflow")
print("-" * 80)
artifact = pot.build_artifact(
    text=question,
    question=question,
    through_stage="knowledge_base",
)
print(f"Foundation stages complete: {artifact.completed_stages}")

pot.run_stage(artifact, "scenario", rerun_downstream=True)
result_staged = pot.execute_artifact(artifact, save_program=True)

print(f"Answer: {result_staged.answer}")
print(f"Success: {result_staged.success}")
print(f"SAT count: {result_staged.sat_count}")
print(f"UNSAT count: {result_staged.unsat_count}")

if not result_staged.success:
    print(f"Error: {result_staged.error}")
    raise SystemExit(1)

# Compare results
print("\n" + "=" * 80)
print("COMPARISON")
print("=" * 80)
print(f"One-shot answer: {result_direct.answer}")
print(f"Explicit staged answer: {result_staged.answer}")
print(f"Answers match: {result_direct.answer == result_staged.answer}")
