#!/usr/bin/env python3
"""
Staged Autoformalization Example using Azure OpenAI.

This demonstrates the new staged SMT-LIB generation pipeline where:
1. LLM generates SMT-LIB in stages (sorts → functions → constants → KB → scenario → query)
2. IR tracks what has been generated for context preservation
3. Each stage receives context from previous stages

Usage:
    python examples/staged_autoformalization.py
    python examples/staged_autoformalization.py --simple
"""

import logging
import sys
from pathlib import Path

# Add parent and utils to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "utils"))

from azure_config import get_azure_client, DEPLOYMENT_NAME
from z3adapter.backends.smt2 import (
    StagedGenerator,
    StagedSMT2Backend,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class AzureOpenAIClient:
    """Wrapper for Azure OpenAI that matches the LLMClient protocol."""

    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def generate(self, prompt: str) -> str:
        """Generate text from prompt using Azure OpenAI."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=4096,
        )
        return response.choices[0].message.content


def run_staged_autoformalization():
    """Run the staged autoformalization example."""

    print("=" * 80)
    print("STAGED SMT-LIB AUTOFORMALIZATION")
    print("=" * 80)

    # Initialize Azure OpenAI client
    print("\n[1] Initializing Azure OpenAI client...")
    azure_client = get_azure_client()
    llm_client = AzureOpenAIClient(azure_client, DEPLOYMENT_NAME)
    print(f"    Model: {DEPLOYMENT_NAME}")

    # Initialize the staged generator
    print("\n[2] Initializing staged generator...")
    generator = StagedGenerator(llm_client)

    # Define the text and question
    text = """
    Changes to the spelling of the names on the ticket must be submitted
    via email within 24 hours of ticket purchase. Requests submitted after
    this window or through other channels (such as phone or in-person)
    will not be processed.
    """

    question = """
    I noticed my last name is misspelled on the ticket I purchased yesterday.
    I'm currently in person at the airport. Can I submit the spelling change
    request in person at the ticket counter?
    """

    print("\n[3] Input:")
    print(f"    Text: {text.strip()[:100]}...")
    print(f"    Question: {question.strip()[:80]}...")

    # Run staged generation
    print("\n[4] Running staged generation...")
    print("-" * 60)

    result = generator.generate(text.strip(), question.strip())

    # Show results for each stage
    print("\n[5] Stage Outputs:")
    for stage_name, output in result.stage_outputs.items():
        print(f"\n    --- {stage_name.upper()} ---")
        # Show first 500 chars of each stage
        lines = output.strip().split('\n')
        for line in lines[:10]:
            print(f"    {line}")
        if len(lines) > 10:
            print(f"    ... ({len(lines) - 10} more lines)")

    # Show context summary
    print("\n[6] Conversion Context (IR):")
    print(result.context.to_summary())

    # Show the complete program
    print("\n[7] Complete SMT-LIB Program:")
    print("-" * 60)
    print(result.smt2_program)
    print("-" * 60)

    # Execute with Z3 if available
    print("\n[8] Executing with Z3...")
    try:
        backend = StagedSMT2Backend()
        verify_result = backend.execute_from_string(result.smt2_program)

        print(f"    Success: {verify_result.success}")
        print(f"    SAT count: {verify_result.sat_count}")
        print(f"    UNSAT count: {verify_result.unsat_count}")
        print(f"    Answer: {verify_result.answer}")

        if verify_result.answer is False:
            print("\n    INTERPRETATION: The in-person submission is NOT allowed")
            print("    (contradicts the email-only policy)")
        elif verify_result.answer is True:
            print("\n    INTERPRETATION: The scenario is consistent with the rules")
        else:
            print("\n    INTERPRETATION: Result is ambiguous")

    except FileNotFoundError as e:
        print(f"    Z3 not available: {e}")
        print("    Skipping execution step.")

    # Show any errors
    if result.errors:
        print("\n[9] Errors:")
        for error in result.errors:
            print(f"    - {error}")

    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)

    return result


def run_simple_example():
    """Run a simpler example for quick testing."""

    print("=" * 80)
    print("SIMPLE STAGED AUTOFORMALIZATION")
    print("=" * 80)

    # Initialize
    azure_client = get_azure_client()
    llm_client = AzureOpenAIClient(azure_client, DEPLOYMENT_NAME)
    generator = StagedGenerator(llm_client)

    # Simple example
    text = "All humans are mortal. Socrates is a human."
    question = "Is Socrates mortal?"

    print(f"\nText: {text}")
    print(f"Question: {question}")
    print("\nGenerating SMT-LIB...")

    result = generator.generate(text, question)

    print("\n--- Generated SMT-LIB ---")
    print(result.smt2_program)

    print("\n--- Context Summary ---")
    print(result.context.to_summary())

    # Execute
    try:
        backend = StagedSMT2Backend()
        verify_result = backend.execute_from_string(result.smt2_program)
        print(f"\nZ3 Result: {'SAT' if verify_result.answer else 'UNSAT' if verify_result.answer is False else 'UNKNOWN'}")
    except Exception as e:
        print(f"\nZ3 execution error: {e}")

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Staged SMT-LIB Autoformalization")
    parser.add_argument("--simple", action="store_true", help="Run simple example")
    args = parser.parse_args()

    if args.simple:
        run_simple_example()
    else:
        run_staged_autoformalization()
