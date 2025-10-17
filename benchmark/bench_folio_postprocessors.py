#!/usr/bin/env python3
"""Benchmark: FOLIO with Postprocessors - Comparing Different Techniques

This script evaluates all four postprocessing techniques on FOLIO to determine
which ones provide the best improvement on this challenging reasoning dataset.

Postprocessors tested:
1. Baseline (no postprocessing)
2. Self-Refine
3. Self-Consistency
4. Decomposed Prompting
5. Least-to-Most Prompting
6. Combined (Self-Refine + Self-Consistency)

FOLIO (First-Order Logic in Natural Language) is a human-annotated dataset
for evaluating natural language reasoning with first-order logic.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Literal

# Add parent directory to path for z3adapter imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.azure_config import get_client_config
from z3adapter.reasoning import EvaluationPipeline, ProofOfThought

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def preprocess_folio(jsonl_path: str, output_path: str) -> None:
    """Preprocess FOLIO to combine premises + conclusion and filter Uncertain labels."""
    with open(jsonl_path) as f:
        data = [json.loads(line) for line in f]

    print(f"Total samples: {len(data)}")

    # Filter out Uncertain labels for binary classification
    data_filtered = [item for item in data if item["label"] != "Uncertain"]

    print(f"After filtering Uncertain: {len(data_filtered)}")

    label_counts: dict[str, int] = {}
    for item in data_filtered:
        label_counts[item["label"]] = label_counts.get(item["label"], 0) + 1
    print(f"Label distribution: {label_counts}")

    processed = []
    for item in data_filtered:
        full_question = f"Given the following premises:\n\n{item['premises']}\n\nAssuming all premises are true, is the following statement true or false?\n\nStatement: {item['conclusion']}"

        answer_bool = item["label"] == "True"

        processed.append(
            {
                "id": f"folio_{item['example_id']}",
                "question": full_question,
                "answer": answer_bool,
                "story_id": item["story_id"],
                "example_id": item["example_id"],
                "original_premises": item["premises"],
                "original_conclusion": item["conclusion"],
            }
        )

    with open(output_path, "w") as f:
        json.dump(processed, f, indent=2)

    print(f"Preprocessed {len(processed)} FOLIO examples")
    print(f"Saved to: {output_path}")


# Preprocess the dataset
jsonl_file = "data/folio_v2_train.jsonl"
processed_file = "data/folio_v2_train_processed.json"

print("Preprocessing FOLIO dataset...")
preprocess_folio(jsonl_file, processed_file)
print()

# Get Azure OpenAI configuration
config = get_client_config()

# Backend selection
BACKEND: Literal["json", "smt2"] = "smt2"  # Options: "smt2" or "json"

# Number of samples to test (use smaller number for faster testing)
MAX_SAMPLES = 50  # Use 100 for full evaluation

# Configuration for each postprocessor experiment
EXPERIMENTS: list[dict[str, Any]] = [
    {
        "name": "Baseline (No Postprocessing)",
        "postprocessors": None,
        "configs": None,
    },
    {
        "name": "Self-Refine",
        "postprocessors": ["self_refine"],
        "configs": {"self_refine": {"num_iterations": 2}},
    },
    {
        "name": "Self-Consistency",
        "postprocessors": ["self_consistency"],
        "configs": {"self_consistency": {"num_samples": 5}},
    },
    {
        "name": "Decomposed Prompting",
        "postprocessors": ["decomposed"],
        "configs": {"decomposed": {"max_subquestions": 3}},
    },
    {
        "name": "Least-to-Most Prompting",
        "postprocessors": ["least_to_most"],
        "configs": {"least_to_most": {"max_steps": 3}},
    },
    {
        "name": "Combined (Self-Refine + Self-Consistency)",
        "postprocessors": ["self_refine", "self_consistency"],
        "configs": {
            "self_refine": {"num_iterations": 2},
            "self_consistency": {"num_samples": 3},
        },
    },
]

# Store results for comparison
all_results: list[dict[str, Any]] = []

print("=" * 80)
print("FOLIO POSTPROCESSOR EVALUATION")
print("=" * 80)
print(f"Backend: {BACKEND.upper()}")
print(f"Model: {config['model']}")
print(f"Samples per experiment: {MAX_SAMPLES}")
print(f"Total experiments: {len(EXPERIMENTS)}")
print("=" * 80)
print()

# Run each experiment
for i, experiment in enumerate(EXPERIMENTS, 1):
    print(f"\n{'=' * 80}")
    print(f"EXPERIMENT {i}/{len(EXPERIMENTS)}: {experiment['name']}")
    print("=" * 80)

    # Create ProofOfThought instance
    pot = ProofOfThought(
        llm_client=config["llm_client"],
        model=config["model"],
        backend=BACKEND,
        max_attempts=3,
        cache_dir=f"output/{BACKEND}_programs_folio_postproc_{i}",
        z3_path="z3",
        postprocessors=experiment["postprocessors"],
        postprocessor_configs=experiment["configs"],
    )

    # Create evaluation pipeline
    evaluator = EvaluationPipeline(
        proof_of_thought=pot,
        output_dir=f"output/{BACKEND}_evaluation_folio_postproc_{i}",
        num_workers=10,  # Sequential for postprocessors (they already parallelize internally)
    )

    # Run evaluation
    eval_result = evaluator.evaluate(
        dataset=processed_file,
        question_field="question",
        answer_field="answer",
        id_field="id",
        max_samples=MAX_SAMPLES,
        skip_existing=False,  # Don't skip to ensure fresh results
    )

    # Store results
    experiment_result: dict[str, Any] = {
        "name": experiment["name"],
        "postprocessors": experiment["postprocessors"],
        "configs": experiment["configs"],
        "metrics": {
            "accuracy": eval_result.metrics.accuracy,
            "precision": eval_result.metrics.precision,
            "recall": eval_result.metrics.recall,
            "f1_score": eval_result.metrics.f1_score,
            "total_samples": eval_result.metrics.total_samples,
            "correct": eval_result.metrics.correct_answers,
            "wrong": eval_result.metrics.wrong_answers,
            "failed": eval_result.metrics.failed_answers,
            "tp": eval_result.metrics.tp,
            "tn": eval_result.metrics.tn,
            "fp": eval_result.metrics.fp,
            "fn": eval_result.metrics.fn,
        },
    }
    all_results.append(experiment_result)

    # Print immediate results
    print(f"\nResults for {experiment['name']}:")
    print(f"  Accuracy: {eval_result.metrics.accuracy:.2%}")
    print(f"  Precision: {eval_result.metrics.precision:.4f}")
    print(f"  Recall: {eval_result.metrics.recall:.4f}")
    print(f"  F1 Score: {eval_result.metrics.f1_score:.4f}")
    print(
        f"  Correct/Wrong/Failed: {eval_result.metrics.correct_answers}/{eval_result.metrics.wrong_answers}/{eval_result.metrics.failed_answers}"
    )

# Save all results to JSON
results_file = f"output/folio_postprocessor_comparison_{BACKEND}.json"
with open(results_file, "w") as f:
    json.dump(all_results, f, indent=2)

print("\n" + "=" * 80)
print("FINAL COMPARISON - ALL POSTPROCESSORS")
print("=" * 80)
print()

# Print comparison table
print(f"{'Technique':<40} {'Accuracy':<12} {'F1 Score':<12} {'Success Rate':<15}")
print("-" * 80)

baseline_accuracy = all_results[0]["metrics"]["accuracy"]

for result in all_results:
    name = result["name"]
    accuracy = result["metrics"]["accuracy"]
    f1 = result["metrics"]["f1_score"]
    total = result["metrics"]["total_samples"]
    failed = result["metrics"]["failed"]
    success_rate = (total - failed) / total if total > 0 else 0

    # Calculate improvement over baseline
    improvement = ""
    if name != "Baseline (No Postprocessing)":
        diff = accuracy - baseline_accuracy
        improvement = f" ({diff:+.1%})"

    print(f"{name:<40} {accuracy:.2%}{improvement:<8} {f1:.4f}      {success_rate:.2%}")

print("-" * 80)
print()

# Find best technique
best_result = max(all_results[1:], key=lambda x: x["metrics"]["accuracy"])  # Skip baseline
print(f"Best Postprocessor: {best_result['name']}")
print(f"  Accuracy: {best_result['metrics']['accuracy']:.2%}")
print(f"  Improvement over baseline: {best_result['metrics']['accuracy'] - baseline_accuracy:+.2%}")
print()

# Save summary
summary = {
    "backend": BACKEND,
    "model": config["model"],
    "max_samples": MAX_SAMPLES,
    "baseline_accuracy": baseline_accuracy,
    "best_technique": best_result["name"],
    "best_accuracy": best_result["metrics"]["accuracy"],
    "improvement": best_result["metrics"]["accuracy"] - baseline_accuracy,
    "all_results": all_results,
}

summary_file = f"output/folio_postprocessor_summary_{BACKEND}.json"
with open(summary_file, "w") as f:
    json.dump(summary, f, indent=2)

print("Results saved to:")
print(f"  - {results_file}")
print(f"  - {summary_file}")
print()
