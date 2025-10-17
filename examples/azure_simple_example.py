#!/usr/bin/env python3
"""
Simplest way to use Azure OpenAI GPT-5 with ProofOfThought.

This example shows the easiest method using the azure_config helper.
"""

import logging

# Import Azure configuration helper
from azure_config import get_client_config

from z3adapter.reasoning import ProofOfThought

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Get Azure GPT-5 configuration (simplest way!)
config = get_client_config()

# Create ProofOfThought with Azure GPT-5
pot = ProofOfThought(llm_client=config["llm_client"], model=config["model"])

# Ask questions
questions = [
    "Would Nancy Pelosi publicly denounce abortion?",
    "Can fish breathe underwater?",
    "Would a student of the class of 2017 remember 9/11?",
]

print("=" * 80)
print("AZURE OPENAI GPT-5 REASONING")
print("=" * 80)

for i, question in enumerate(questions, 1):
    print(f"\n[{i}/{len(questions)}] {question}")
    result = pot.query(question)
    print(f"  Answer: {result.answer}")
    print(f"  Success: {result.success}")
    print(f"  Attempts: {result.num_attempts}")

    if not result.success:
        print(f"  Error: {result.error}")
