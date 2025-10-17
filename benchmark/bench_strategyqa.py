#!/usr/bin/env python3
"""Benchmark: StrategyQA with SMT2 backend and Azure OpenAI.

StrategyQA is a question answering benchmark that focuses on open-domain
questions where the required reasoning steps are implicit in the question
and should be inferred using a strategy.
"""

import logging
import sys
from pathlib import Path
from typing import Literal

# Add parent directory to path for z3adapter imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.azure_config import get_client_config
from z3adapter.reasoning import EvaluationPipeline, ProofOfThought

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Get Azure OpenAI configuration
config = get_client_config()

# Backend selection (change this to "json" to test JSON backend)
BACKEND: Literal["json", "smt2"] = "json"  # Options: "smt2" or "json"

# Create ProofOfThought instance with configurable backend
pot = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend=BACKEND,
    max_attempts=3,
    cache_dir=f"output/{BACKEND}_programs_strategyqa",
    z3_path="z3",
)

# Create evaluation pipeline with parallel workers
evaluator = EvaluationPipeline(
    proof_of_thought=pot,
    output_dir=f"output/{BACKEND}_evaluation_strategyqa",
    num_workers=10,
)

# Run evaluation
result = evaluator.evaluate(
    dataset="data/strategyQA_train.json",
    question_field="question",
    answer_field="answer",
    id_field="qid",
    max_samples=100,
    skip_existing=True,
)

# Print results
print("\n" + "=" * 80)
print(f"STRATEGYQA BENCHMARK RESULTS ({BACKEND.upper()} Backend + Azure GPT-5)")
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
