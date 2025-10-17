#!/usr/bin/env python3
"""Example: Simple usage of ProofOfThought API."""

import logging
import os

from openai import OpenAI

from z3adapter.reasoning import ProofOfThought

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Option 1: Standard OpenAI
# Set OPENAI_API_KEY in your .env file
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError(
        "OPENAI_API_KEY is not set. " "Please set it in your .env file or environment variables."
    )

client = OpenAI(api_key=api_key)
pot = ProofOfThought(llm_client=client, model="gpt-4o")

# Option 2: Azure OpenAI GPT-5 (uncomment to use)
# from utils.azure_config import get_client_config
# config = get_client_config()
# pot = ProofOfThought(llm_client=config["llm_client"], model=config["model"])

# Ask a question
question = "Would Nancy Pelosi publicly denounce abortion?"
result = pot.query(question)

# Print results
print("\n" + "=" * 80)
print("QUERY RESULTS")
print("=" * 80)
print(f"Question: {result.question}")
print(f"Answer: {result.answer}")
print(f"Success: {result.success}")
print(f"Attempts: {result.num_attempts}")
print(f"SAT count: {result.sat_count}")
print(f"UNSAT count: {result.unsat_count}")

if result.error:
    print(f"Error: {result.error}")

if result.json_program:
    print("\nGenerated JSON program structure:")
    print(f"  - Sorts: {len(result.json_program.get('sorts', []))}")
    print(f"  - Functions: {len(result.json_program.get('functions', []))}")
    print(f"  - Constants: {len(result.json_program.get('constants', {}))}")
    print(f"  - Knowledge base: {len(result.json_program.get('knowledge_base', []))}")
    print(f"  - Verifications: {len(result.json_program.get('verifications', []))}")
