#!/usr/bin/env python3
"""Example: Using Postprocessors to Improve Reasoning Quality

This example demonstrates how to use postprocessing techniques to enhance
the quality and reliability of reasoning results.

All postprocessors work with both JSON and SMT2 backends.
"""

import sys
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.azure_config import get_client_config
from z3adapter.postprocessors import SelfRefine
from z3adapter.postprocessors.registry import PostprocessorRegistry
from z3adapter.reasoning import ProofOfThought

# Get Azure OpenAI configuration
config = get_client_config()

print("=" * 80)
print("Postprocessor Demonstration")
print("=" * 80)
print()

# Test question (complex reasoning)
question = """Given the following premises:

All people who regularly drink coffee are dependent on caffeine.
People regularly drink coffee, or they don't want to be addicted to caffeine, or both.
No one who doesn't want to be addicted to caffeine is unaware that caffeine is a drug.
Rina is either a student who is unaware that caffeine is a drug, or she is not a student and is aware that caffeine is a drug.
Rina is either a student who is dependent on caffeine, or she is not a student and not dependent on caffeine.

Assuming all premises are true, is the following statement true or false?

Statement: Rina doesn't want to be addicted to caffeine or is unaware that caffeine is a drug."""

# Example 1: Baseline (no postprocessing)
print("Example 1: Baseline (No Postprocessing)")
print("-" * 80)

pot_baseline = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="smt2",
)

result_baseline = pot_baseline.query(question)
print(f"Answer: {result_baseline.answer}")
print(f"Success: {result_baseline.success}")
print(f"Attempts: {result_baseline.num_attempts}")
print()

# Example 2: Self-Refine
print("Example 2: With Self-Refine Postprocessor")
print("-" * 80)

pot_refine = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="smt2",
    postprocessors=["self_refine"],
    postprocessor_configs={"self_refine": {"num_iterations": 2}},
)

result_refine = pot_refine.query(question)
print(f"Answer: {result_refine.answer}")
print(f"Success: {result_refine.success}")
print()

# Example 3: Self-Consistency
print("Example 3: With Self-Consistency Postprocessor")
print("-" * 80)

pot_consistency = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="smt2",
    postprocessors=["self_consistency"],
    postprocessor_configs={"self_consistency": {"num_samples": 5}},
)

result_consistency = pot_consistency.query(question)
print(f"Answer: {result_consistency.answer}")
print(f"Success: {result_consistency.success}")
print()

# Example 4: Decomposed Prompting
print("Example 4: With Decomposed Prompting Postprocessor")
print("-" * 80)

pot_decomposed = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="smt2",
    postprocessors=["decomposed"],
    postprocessor_configs={"decomposed": {"max_subquestions": 3}},
)

result_decomposed = pot_decomposed.query(question)
print(f"Answer: {result_decomposed.answer}")
print(f"Success: {result_decomposed.success}")
print()

# Example 5: Least-to-Most Prompting
print("Example 5: With Least-to-Most Prompting Postprocessor")
print("-" * 80)

pot_least_to_most = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="smt2",
    postprocessors=["least_to_most"],
    postprocessor_configs={"least_to_most": {"max_steps": 3}},
)

result_least_to_most = pot_least_to_most.query(question)
print(f"Answer: {result_least_to_most.answer}")
print(f"Success: {result_least_to_most.success}")
print()

# Example 6: Multiple postprocessors (chained)
print("Example 6: Multiple Postprocessors (Self-Refine + Self-Consistency)")
print("-" * 80)

pot_combined = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="smt2",
    postprocessors=["self_refine", "self_consistency"],
    postprocessor_configs={
        "self_refine": {"num_iterations": 2},
        "self_consistency": {"num_samples": 3},
    },
)

result_combined = pot_combined.query(question)
print(f"Answer: {result_combined.answer}")
print(f"Success: {result_combined.success}")
print()

# Example 7: Using postprocessor instances directly
print("Example 7: Using Postprocessor Instances Directly")
print("-" * 80)

custom_refine = SelfRefine(num_iterations=3, name="CustomRefine")

pot_custom = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="smt2",
    postprocessors=[custom_refine],  # Pass instance instead of string
)

result_custom = pot_custom.query(question)
print(f"Answer: {result_custom.answer}")
print(f"Success: {result_custom.success}")
print()

# Example 8: Disable postprocessing per query
print("Example 8: Disabling Postprocessing for a Specific Query")
print("-" * 80)

# Even though pot_refine has postprocessors configured,
# we can disable them for individual queries
result_no_postprocess = pot_refine.query(question, enable_postprocessing=False)
print(f"Answer: {result_no_postprocess.answer}")
print(f"Success: {result_no_postprocess.success}")
print("(Postprocessing was disabled for this query)")
print()

# Summary
print("=" * 80)
print("Summary")
print("=" * 80)
print()
print("All postprocessors are backend-agnostic and work with both JSON and SMT2.")
print("They can be:")
print("  - Enabled at ProofOfThought initialization")
print("  - Configured with custom parameters")
print("  - Chained together for combined benefits")
print("  - Disabled per-query when needed")
print()
print("Available postprocessors:")

for name in PostprocessorRegistry.list_available():
    config = PostprocessorRegistry.get_default_config(name)
    print(f"  - {name}: {config}")
