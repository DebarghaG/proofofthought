#!/usr/bin/env python3
"""
Compare JSON and SMT2 backends with ProofOfThought.

This example demonstrates using both backends on the same question.
"""

import logging
import sys
from pathlib import Path

# Add parent directory to path for z3adapter imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import Azure configuration helper
from azure_config import get_client_config

from z3adapter.reasoning import ProofOfThought

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Get Azure GPT-5 configuration
config = get_client_config()

# Test question
question = "Can fish breathe underwater?"

print("=" * 80)
print("BACKEND COMPARISON: JSON vs SMT2")
print("=" * 80)

# Test with JSON backend
print("\n[1/2] Testing JSON Backend")
print("-" * 80)
pot_json = ProofOfThought(llm_client=config["llm_client"], model=config["model"], backend="json")

result_json = pot_json.query(question, save_program=True)
print(f"Question: {question}")
print(f"Answer: {result_json.answer}")
print(f"Success: {result_json.success}")
print(f"Attempts: {result_json.num_attempts}")
print(f"SAT count: {result_json.sat_count}")
print(f"UNSAT count: {result_json.unsat_count}")

if not result_json.success:
    print(f"Error: {result_json.error}")
    sys.exit(1)

# Test with SMT2 backend
print("\n[2/2] Testing SMT2 Backend")
print("-" * 80)
pot_smt2 = ProofOfThought(llm_client=config["llm_client"], model=config["model"], backend="smt2")

result_smt2 = pot_smt2.query(question, save_program=True)
print(f"Question: {question}")
print(f"Answer: {result_smt2.answer}")
print(f"Success: {result_smt2.success}")
print(f"Attempts: {result_smt2.num_attempts}")
print(f"SAT count: {result_smt2.sat_count}")
print(f"UNSAT count: {result_smt2.unsat_count}")

if not result_smt2.success:
    print(f"Error: {result_smt2.error}")
    sys.exit(1)

# Compare results
print("\n" + "=" * 80)
print("COMPARISON")
print("=" * 80)
print(f"JSON Answer: {result_json.answer}")
print(f"SMT2 Answer: {result_smt2.answer}")
print(f"Answers Match: {result_json.answer == result_smt2.answer}")

if result_json.answer == result_smt2.answer:
    print("\n✓ Both backends produced the same answer!")
else:
    print("\n✗ WARNING: Backends produced different answers!")
