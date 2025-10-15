#!/usr/bin/env python3
"""Example: Batch evaluation on StrategyQA using SMT2 backend with Azure OpenAI."""

import logging
import sys
from pathlib import Path

# Add parent directory to path for z3dsl imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from azure_config import get_client_config

from z3dsl.reasoning import EvaluationPipeline, ProofOfThought

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Get Azure OpenAI configuration
config = get_client_config()

# Create ProofOfThought instance with SMT2 backend
pot = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="smt2",  # ← Use SMT2 backend
    max_attempts=3,
    cache_dir="output/programs_smt2",
    z3_path="z3",
)

# Create evaluation pipeline with 10 parallel workers
evaluator = EvaluationPipeline(
    proof_of_thought=pot,
    output_dir="output/evaluation_results_smt2",
    num_workers=10,  # Run 10 LLM generations in parallel
)

# Run evaluation
result = evaluator.evaluate(
    dataset="examples/strategyQA_train.json",
    question_field="question",
    answer_field="answer",
    id_field="qid",
    max_samples=100,
    skip_existing=True,
)

# Print results
print("\n" + "=" * 80)
print("EVALUATION METRICS (SMT2 Backend + Azure GPT-5)")
print("=" * 80)
print(f"Total Samples: {result.metrics.total_samples}")
print(f"Correct: {result.metrics.correct_answers}")
print(f"Wrong: {result.metrics.wrong_answers}")
print(f"Failed: {result.metrics.failed_answers}")
print()
print(f"Accuracy: {result.metrics.accuracy:.2%}")
print(f"Precision: {result.metrics.precision:.4f}")
print(f"Recall: {result.metrics.recall:.4f}")
print(f"F1 Score: {result.metrics.f1_score:.4f}")
