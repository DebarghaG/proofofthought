#!/usr/bin/env python3
"""Benchmark: StrategyQA with SMT2 backend and Azure OpenAI.

StrategyQA is a question answering benchmark that focuses on open-domain
questions where the required reasoning steps are implicit in the question
and should be inferred using a strategy.
"""

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
    backend="smt2",
    max_attempts=3,
    cache_dir="output/programs_smt2_strategyqa",
    z3_path="z3",
)

# Create evaluation pipeline with parallel workers
evaluator = EvaluationPipeline(
    proof_of_thought=pot,
    output_dir="output/evaluation_results_strategyqa",
    num_workers=10,
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
print("STRATEGYQA BENCHMARK RESULTS (SMT2 Backend + Azure GPT-5)")
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
print(f"Specificity: {result.metrics.specificity:.4f}")
print()
print(f"True Positives: {result.metrics.tp}")
print(f"True Negatives: {result.metrics.tn}")
print(f"False Positives: {result.metrics.fp}")
print(f"False Negatives: {result.metrics.fn}")
print("=" * 80)
