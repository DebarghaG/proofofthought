#!/usr/bin/env python3
"""
Experiments Pipeline: Run all benchmarks with both backends and generate results table.
Note : This makes a fair number of LLM calls and is only for benchmarking.

This script:
1. Runs all benchmarks (ProntoQA, FOLIO, ProofWriter, ConditionalQA, StrategyQA)
2. Tests both backends (SMT2 and JSON)
3. Collects metrics and generates comparison tables
4. Updates README.md with results
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from typing import Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration
BENCHMARKS = {
    "prontoqa": "benchmark/bench_prontoqa.py",
    "folio": "benchmark/bench_folio.py",
    "proofwriter": "benchmark/bench_proofwriter.py",
    "conditionalqa": "benchmark/bench_conditionalqa.py",
    "strategyqa": "benchmark/bench_strategyqa.py",
}

BACKENDS = ["smt2", "json"]
RESULTS_DIR = "results"
RESULTS_TABLE_PATH = os.path.join(RESULTS_DIR, "benchmark_results.md")
RESULTS_JSON_PATH = os.path.join(RESULTS_DIR, "benchmark_results.json")


def modify_backend_in_script(script_path: str, backend: str) -> None:
    """Temporarily modify the BACKEND variable in a benchmark script.

    Args:
        script_path: Path to benchmark script
        backend: Backend to set ("smt2" or "json")
    """
    with open(script_path) as f:
        content = f.read()

    # Replace BACKEND = "..." with new value
    import re

    modified = re.sub(r'BACKEND = "[^"]*"', f'BACKEND = "{backend}"', content)

    with open(script_path, "w") as f:
        f.write(modified)

    logger.info(f"Modified {script_path} to use backend={backend}")


def run_benchmark(benchmark_name: str, script_path: str, backend: str) -> bool:
    """Run a single benchmark script.

    Args:
        benchmark_name: Name of benchmark
        script_path: Path to benchmark script
        backend: Backend to use

    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Running {benchmark_name} with {backend} backend...")

    try:
        # Modify script to use correct backend
        modify_backend_in_script(script_path, backend)

        # Run the benchmark
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour timeout
        )

        if result.returncode != 0:
            logger.error(f"Benchmark {benchmark_name} failed with backend {backend}")
            logger.error(f"STDERR: {result.stderr}")
            return False

        logger.info(f"Completed {benchmark_name} with {backend} backend")
        return True

    except subprocess.TimeoutExpired:
        logger.error(f"Benchmark {benchmark_name} timed out with backend {backend}")
        return False
    except Exception as e:
        logger.error(f"Error running {benchmark_name} with {backend}: {e}")
        return False


def collect_metrics(benchmark_name: str, backend: str) -> dict[str, Any] | None:
    """Collect metrics from evaluation results.

    Args:
        benchmark_name: Name of benchmark
        backend: Backend used

    Returns:
        Dictionary of metrics or None if not found
    """
    eval_dir = f"output/{backend}_evaluation_{benchmark_name}"

    if not os.path.exists(eval_dir):
        logger.warning(f"Results directory not found: {eval_dir}")
        return None

    # Collect all result files
    result_files = [f for f in os.listdir(eval_dir) if f.endswith("_result.json")]

    if not result_files:
        logger.warning(f"No result files found in {eval_dir}")
        return None

    # Parse results
    total = 0
    correct = 0
    wrong = 0
    failed = 0
    tp = 0
    tn = 0
    fp = 0
    fn = 0

    for result_file in result_files:
        try:
            with open(os.path.join(eval_dir, result_file)) as f:
                data = json.load(f)

            total += 1
            ground_truth = data.get("ground_truth")
            answer = data.get("answer")
            success = data.get("success")

            if not success or answer is None:
                failed += 1
                continue

            if answer == ground_truth:
                correct += 1
                if ground_truth:
                    tp += 1
                else:
                    tn += 1
            else:
                wrong += 1
                if answer:
                    fp += 1
                else:
                    fn += 1

        except Exception as e:
            logger.warning(f"Failed to parse {result_file}: {e}")
            continue

    # Calculate metrics
    accuracy = correct / total if total > 0 else 0.0

    # Precision, Recall, F1
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    success_rate = (total - failed) / total if total > 0 else 0.0

    return {
        "benchmark": benchmark_name,
        "backend": backend,
        "total_samples": total,
        "correct": correct,
        "wrong": wrong,
        "failed": failed,
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1_score": f1,
        "success_rate": success_rate,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
    }


def generate_markdown_table(all_results: list[dict[str, Any]]) -> str:
    """Generate markdown table from results.

    Args:
        all_results: List of result dictionaries

    Returns:
        Markdown formatted table
    """
    lines = [
        "# Benchmark Results",
        "",
        f"**Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "| Benchmark | Backend | Samples | Accuracy | Precision | Recall | F1 Score | Success Rate |",
        "|-----------|---------|---------|----------|-----------|--------|----------|--------------|",
    ]

    for result in all_results:
        line = (
            f"| {result['benchmark'].upper()} "
            f"| {result['backend'].upper()} "
            f"| {result['total_samples']} "
            f"| {result['accuracy']:.2%} "
            f"| {result['precision']:.4f} "
            f"| {result['recall']:.4f} "
            f"| {result['f1_score']:.4f} "
            f"| {result['success_rate']:.2%} |"
        )
        lines.append(line)

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- **Success Rate**: Percentage of queries that completed without errors",
            "",
        ]
    )

    return "\n".join(lines)


def update_readme(table_content: str) -> None:
    """Update README.md with benchmark results.

    Args:
        table_content: Markdown table content
    """
    readme_path = "README.md"

    with open(readme_path) as f:
        readme_content = f.read()

    # Check if markers exist
    start_marker = "<!-- BENCHMARK_RESULTS_START -->"
    end_marker = "<!-- BENCHMARK_RESULTS_END -->"

    if start_marker in readme_content and end_marker in readme_content:
        # Replace existing content
        import re

        pattern = f"{re.escape(start_marker)}.*?{re.escape(end_marker)}"
        replacement = f"{start_marker}\n\n{table_content}\n\n{end_marker}"
        new_content = re.sub(pattern, replacement, readme_content, flags=re.DOTALL)
    else:
        # Append at the end
        new_content = (
            readme_content.rstrip() + f"\n\n{start_marker}\n\n{table_content}\n\n{end_marker}\n"
        )

    with open(readme_path, "w") as f:
        f.write(new_content)

    logger.info("Updated README.md with benchmark results")


def main() -> None:
    """Main execution pipeline."""
    print("=" * 80)
    print("EXPERIMENTS PIPELINE: BENCHMARK ALL DATASETS WITH BOTH BACKENDS")
    print("=" * 80)
    print()

    # Create results directory
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # Track all results
    all_results = []

    # Run benchmarks
    for backend in BACKENDS:
        print(f"\n{'=' * 80}")
        print(f"BACKEND: {backend.upper()}")
        print(f"{'=' * 80}\n")

        for benchmark_name, script_path in BENCHMARKS.items():
            print(f"\n{'-' * 80}")
            print(f"Running {benchmark_name.upper()} with {backend.upper()} backend")
            print(f"{'-' * 80}\n")

            # Run benchmark
            success = run_benchmark(benchmark_name, script_path, backend)

            if not success:
                logger.warning(f"Skipping metrics collection for {benchmark_name} ({backend})")
                continue

            # Collect metrics
            metrics = collect_metrics(benchmark_name, backend)
            if metrics:
                all_results.append(metrics)
                logger.info(f"Collected metrics for {benchmark_name} ({backend})")
            else:
                logger.warning(f"Failed to collect metrics for {benchmark_name} ({backend})")

    # Generate results table
    if not all_results:
        logger.error("No results collected. Exiting.")
        return

    print("\n" + "=" * 80)
    print("GENERATING RESULTS TABLE")
    print("=" * 80 + "\n")

    # Save JSON results
    with open(RESULTS_JSON_PATH, "w") as f:
        json.dump(all_results, f, indent=2)
    logger.info(f"Saved raw results to {RESULTS_JSON_PATH}")

    # Generate markdown table
    table_content = generate_markdown_table(all_results)

    with open(RESULTS_TABLE_PATH, "w") as f:
        f.write(table_content)
    logger.info(f"Saved markdown table to {RESULTS_TABLE_PATH}")

    # Update README
    update_readme(table_content)

    # Print summary
    print("\n" + "=" * 80)
    print("PIPELINE COMPLETE")
    print("=" * 80)
    print("\nResults saved to:")
    print(f"  - {RESULTS_TABLE_PATH}")
    print(f"  - {RESULTS_JSON_PATH}")
    print("  - README.md (updated)")
    print()
    print("Summary:")
    print(f"  - Total benchmarks run: {len(all_results)}")
    print(f"  - Backends tested: {', '.join(BACKENDS)}")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nPipeline interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
