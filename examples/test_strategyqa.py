#!/usr/bin/env python3
"""
Benchmark ProofOfThought on StrategyQA dataset.
Tests the first 100 questions and tracks performance metrics.
"""

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from examples.azure_config import get_client_config
from z3adapter.reasoning import ProofOfThought

# Configure logging
logging.basicConfig(
    level=logging.WARNING,  # Reduce noise, only show warnings and errors
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def load_strategyqa_questions(dataset_path: str, num_questions: int = 100) -> list[dict[str, Any]]:
    """Load questions from StrategyQA dataset."""
    with open(dataset_path) as f:
        data = json.load(f)

    questions = []
    for item in data[:num_questions]:
        questions.append(
            {
                "qid": item["qid"],
                "question": item["question"],
                "answer": item["answer"],
                "facts": item.get("facts", []),
                "decomposition": item.get("decomposition", []),
            }
        )

    return questions


def run_benchmark(
    questions: list[dict[str, Any]], pot: Any
) -> tuple[list[dict[str, Any]], int, int, int]:
    """Run ProofOfThought on all questions and collect results."""
    results = []
    successful = 0
    correct = 0
    total_attempts = 0

    print(f"\n{'='*80}")
    print(f"STRATEGYQA BENCHMARK - Testing {len(questions)} questions")
    print(f"{'='*80}\n")

    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q['question']}")

        start_time = time.time()
        try:
            result = pot.query(q["question"])
            elapsed = time.time() - start_time

            # Convert answer to boolean (True/False)
            predicted = result.answer
            expected = q["answer"]

            is_correct = predicted == expected if predicted is not None else False

            if result.success:
                successful += 1
                total_attempts += result.num_attempts
                if is_correct:
                    correct += 1
                    print(
                        f"  ✓ Correct! Predicted: {predicted}, Attempts: {result.num_attempts}, Time: {elapsed:.1f}s"
                    )
                else:
                    print(
                        f"  ✗ Wrong! Expected: {expected}, Got: {predicted}, Attempts: {result.num_attempts}"
                    )
            else:
                print(f"  ✗ Failed! Error: {result.error}")

            results.append(
                {
                    "qid": q["qid"],
                    "question": q["question"],
                    "expected": expected,
                    "predicted": predicted,
                    "success": result.success,
                    "correct": is_correct,
                    "num_attempts": result.num_attempts,
                    "elapsed_time": elapsed,
                    "error": result.error,
                }
            )

        except Exception as e:
            elapsed = time.time() - start_time
            print(f"  ✗ Exception: {str(e)}")
            results.append(
                {
                    "qid": q["qid"],
                    "question": q["question"],
                    "expected": q["answer"],
                    "predicted": None,
                    "success": False,
                    "correct": False,
                    "num_attempts": 0,
                    "elapsed_time": elapsed,
                    "error": str(e),
                }
            )

        # Print progress every 10 questions
        if i % 10 == 0:
            current_success_rate = (successful / i) * 100 if i > 0 else 0
            current_accuracy = (correct / successful) * 100 if successful > 0 else 0
            avg_attempts = total_attempts / successful if successful > 0 else 0
            print(
                f"\n  Progress: {i}/{len(questions)} | Success: {current_success_rate:.1f}% | Accuracy: {current_accuracy:.1f}% | Avg Attempts: {avg_attempts:.1f}\n"
            )

    return results, successful, correct, total_attempts


def print_summary(
    results: list[dict[str, Any]], successful: int, correct: int, total_attempts: int
) -> None:
    """Print summary statistics."""
    total = len(results)
    success_rate = (successful / total) * 100 if total > 0 else 0
    accuracy = (correct / successful) * 100 if successful > 0 else 0
    avg_attempts = total_attempts / successful if successful > 0 else 0
    overall_accuracy = (correct / total) * 100 if total > 0 else 0

    print(f"\n{'='*80}")
    print("BENCHMARK SUMMARY")
    print(f"{'='*80}")
    print(f"Total Questions: {total}")
    print(f"Successful Runs: {successful} ({success_rate:.1f}%)")
    print(f"Correct Answers: {correct}")
    print(f"Accuracy (of successful): {accuracy:.1f}%")
    print(f"Overall Accuracy: {overall_accuracy:.1f}%")
    print(f"Average Attempts: {avg_attempts:.2f}")
    print(f"{'='*80}\n")

    # Error breakdown
    errors: dict[str, int] = {}
    for r in results:
        if not r["success"] and r["error"]:
            error_key = r["error"][:50]  # Truncate long errors
            errors[error_key] = errors.get(error_key, 0) + 1

    if errors:
        print("Error Breakdown:")
        for error, count in sorted(errors.items(), key=lambda x: -x[1]):
            print(f"  {count:3d}x: {error}")
        print()


def save_results(results: list[dict[str, Any]], output_path: str) -> None:
    """Save results to JSON file."""
    output = {
        "timestamp": datetime.now().isoformat(),
        "total": len(results),
        "successful": sum(1 for r in results if r["success"]),
        "correct": sum(1 for r in results if r["correct"]),
        "results": results,
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Results saved to: {output_path}")


def main() -> None:
    """Main benchmark execution."""
    script_dir = Path(__file__).parent
    dataset_path = script_dir / "strategyQA_train.json"
    output_path = script_dir / "strategyqa_results.json"
    num_questions = 100

    # Load questions
    print("Loading StrategyQA questions...")
    questions = load_strategyqa_questions(str(dataset_path), num_questions)
    print(f"Loaded {len(questions)} questions")

    # Initialize ProofOfThought with Azure GPT-5
    print("Initializing ProofOfThought with Azure GPT-5...")
    config = get_client_config()
    pot = ProofOfThought(llm_client=config["llm_client"], model=config["model"], max_attempts=3)
    print("Ready!\n")

    # Run benchmark
    start_time = time.time()
    results, successful, correct, total_attempts = run_benchmark(questions, pot)
    total_time = time.time() - start_time

    # Print summary
    print_summary(results, successful, correct, total_attempts)
    print(f"Total execution time: {total_time/60:.1f} minutes\n")

    # Save results
    save_results(results, str(output_path))


if __name__ == "__main__":
    main()
