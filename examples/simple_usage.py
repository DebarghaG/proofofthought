#!/usr/bin/env python3
"""Example: Simple staged usage of ProofOfThought."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from proofofthought import ProofOfThought

project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")

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
output_path = project_root / "output" / "simple_usage.smt2"
artifact_path = project_root / "output" / "simple_usage.artifact.json"
output_path.parent.mkdir(exist_ok=True)
result = pot.query(
    question,
    save_program=True,
    program_path=str(output_path),
    save_artifact=True,
    artifact_path=str(artifact_path),
)

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
if result.failure_code:
    print(f"Failure code: {result.failure_code}")

print(f"Program format: {result.program_format}")
print(f"Program path: {result.program_path}")
print(f"Artifact path: {result.artifact.artifact_path if result.artifact else None}")

if result.smt2_program:
    print(f"SMT-LIB lines: {len(result.smt2_program.splitlines())}")
