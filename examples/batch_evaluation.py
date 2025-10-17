#!/usr/bin/env python3
"""Example: Batch evaluation on StrategyQA dataset."""

import logging
import os

from openai import OpenAI

from z3adapter.reasoning import EvaluationPipeline, ProofOfThought

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
model = "gpt-4o"

# Option 2: Azure OpenAI GPT-5 (uncomment to use)
# from utils.azure_config import get_client_config
# config = get_client_config()
# client = config["llm_client"]
# model = config["model"]

# Create ProofOfThought instance
pot = ProofOfThought(
    llm_client=client,
    model=model,
    max_attempts=3,  # Retry up to 3 times
    cache_dir="output/programs",  # Save generated programs
)

# Create evaluation pipeline
evaluator = EvaluationPipeline(proof_of_thought=pot, output_dir="output/evaluation_results")

# Run evaluation on StrategyQA dataset
result = evaluator.evaluate(
    dataset="strategyqa_train.json",  # Path to dataset
    question_field="question",  # Field name for questions
    answer_field="answer",  # Field name for ground truth
    id_field="qid",  # Field name for question IDs
    max_samples=10,  # Evaluate only first 10 samples
    skip_existing=True,  # Skip already processed samples
)

# Print detailed metrics
print("\n" + "=" * 80)
print("EVALUATION METRICS")
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
print(f"False Positive Rate: {result.metrics.false_positive_rate:.4f}")
print(f"False Negative Rate: {result.metrics.false_negative_rate:.4f}")

# Show sample results
print("\n" + "=" * 80)
print("SAMPLE RESULTS")
print("=" * 80)
for i, query_result in enumerate(result.results[:5]):  # Show first 5
    print(f"\n[{i+1}] {query_result.question}")
    print(f"    Answer: {query_result.answer} (attempts: {query_result.num_attempts})")
    print(f"    Success: {query_result.success}")
