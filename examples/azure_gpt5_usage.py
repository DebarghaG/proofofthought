#!/usr/bin/env python3
"""Example: Using ProofOfThought with Azure OpenAI GPT-5 and the staged query path."""

import logging

from azure_config import get_client_config

from proofofthought import ProofOfThought

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Get Azure GPT-5 configuration from environment variables
config = get_client_config()

# Create ProofOfThought instance with GPT-5
pot = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    max_attempts=3,
    verify_timeout=10000,
)

# Ask a question
question = "Would Nancy Pelosi publicly denounce abortion?"
print(f"\nQuestion: {question}")
print("-" * 80)

result = pot.query(
    question=question,
    temperature=0.1,
    max_tokens=16384,  # GPT-5 supports up to 16K output tokens
    save_program=True,
    program_path="azure_gpt5_program.smt2",
)

# Print results
print("\n" + "=" * 80)
print("GPT-5 QUERY RESULTS")
print("=" * 80)
print(f"Question: {result.question}")
print(f"Answer: {result.answer}")
print(f"Success: {result.success}")
print(f"Attempts: {result.num_attempts}")
print(f"SAT count: {result.sat_count}")
print(f"UNSAT count: {result.unsat_count}")

if result.error:
    print(f"\nError: {result.error}")
if result.failure_code:
    print(f"Failure code: {result.failure_code}")

print(f"Program format: {result.program_format}")
print(f"Program saved to: {result.program_path}")

if result.smt2_program:
    print(f"Generated SMT-LIB lines: {len(result.smt2_program.splitlines())}")

# Demonstrate batch processing with GPT-5
print("\n" + "=" * 80)
print("BATCH PROCESSING WITH GPT-5")
print("=" * 80)

questions = [
    "Can fish breathe underwater?",
    "Would a student of the class of 2017 remember 9/11?",
    "Can elephants fly?",
]

for i, q in enumerate(questions, 1):
    print(f"\n[{i}/{len(questions)}] {q}")
    result = pot.query(q)
    print(f"  Answer: {result.answer} (attempts: {result.num_attempts})")
