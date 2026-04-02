#!/usr/bin/env python3
"""Example: Batch evaluation on StrategyQA using the staged backend with Azure OpenAI."""

import logging
from pathlib import Path

from azure_config import get_client_config

from proofofthought import EvaluationPipeline, ProofOfThought

project_root = Path(__file__).parent.parent

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Get Azure OpenAI configuration
config = get_client_config()

# Create ProofOfThought instance.
# `backend="smt2"` is kept here to show the compatibility alias still works.
pot = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="smt2",
    max_attempts=3,
    cache_dir=str(project_root / "output" / "programs_smt2"),
    z3_path="z3",
)

# Create evaluation pipeline with 10 parallel workers
evaluator = EvaluationPipeline(
    proof_of_thought=pot,
    output_dir=str(project_root / "output" / "evaluation_results_smt2"),
    num_workers=10,  # Run 10 LLM generations in parallel
)

# Run evaluation
result = evaluator.evaluate(
    dataset=str(project_root / "data" / "strategyQA_train.json"),
    question_field="question",
    answer_field="answer",
    id_field="qid",
    max_samples=100,
    skip_existing=True,
)

# Print results
print("\n" + "=" * 80)
print("EVALUATION METRICS (Staged Backend + Azure GPT-5)")
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
