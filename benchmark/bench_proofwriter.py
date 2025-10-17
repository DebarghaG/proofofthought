#!/usr/bin/env python3
"""Benchmark: ProofWriter with SMT2 backend and Azure OpenAI.

ProofWriter is a logical reasoning benchmark consisting of natural language
rulebases (facts and rules) with questions that can be proven true, false,
or unknown. The dataset includes proofs of various depths and complexity.

Dataset: HuggingFace tasksource/proofwriter (test split)
Format: Parquet file with theory (facts/rules), question, and answer (True/False/Unknown)
Note: This script filters out "Unknown" answers for binary classification
"""

import json
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


def preprocess_proofwriter(parquet_path: str, output_path: str, max_samples: int = 1000) -> None:
    """Preprocess ProofWriter to combine theory + question and filter Unknown answers.

    ProofWriter format:
    - theory: Background facts and rules (natural language)
    - question: The query statement
    - answer: "True", "False", or "Unknown"
    - QDep: Question depth (number of reasoning steps)

    Output format:
    - question: theory + "\n\nQuestion: " + question
    - answer: True/False (boolean, "Unknown" samples filtered out)
    - id: original id
    - QDep: reasoning depth
    """
    import pandas as pd

    df = pd.read_parquet(parquet_path)

    # Filter out Unknown answers for binary classification
    df_filtered = df[df["answer"] != "Unknown"].copy()

    print(f"Total samples: {len(df)}")
    print(f"After filtering Unknown: {len(df_filtered)}")
    print(f"Answer distribution: {df_filtered['answer'].value_counts().to_dict()}")

    # Sample for evaluation (balanced if possible)
    if len(df_filtered) > max_samples:
        # Try to get balanced sample
        df_true = df_filtered[df_filtered["answer"] == "True"].sample(
            n=min(max_samples // 2, len(df_filtered[df_filtered["answer"] == "True"])),
            random_state=42,
        )
        df_false = df_filtered[df_filtered["answer"] == "False"].sample(
            n=min(max_samples // 2, len(df_filtered[df_filtered["answer"] == "False"])),
            random_state=42,
        )
        df_filtered = pd.concat([df_true, df_false]).sample(frac=1, random_state=42)

    processed = []
    for _, row in df_filtered.iterrows():
        # Combine theory with question for complete reasoning scenario
        full_question = f"{row['theory']}\n\nQuestion: {row['question']}"

        # Convert string answer to boolean
        answer_bool = row["answer"] == "True"

        processed.append(
            {
                "id": row["id"],
                "question": full_question,
                "answer": answer_bool,
                "QDep": int(row["QDep"]),
                "original_theory": row["theory"],
                "original_question": row["question"],
            }
        )

    with open(output_path, "w") as f:
        json.dump(processed, f, indent=2)

    print(f"Preprocessed {len(processed)} ProofWriter examples")
    print(f"QDep distribution: {df_filtered['QDep'].value_counts().sort_index().to_dict()}")
    print(f"Saved to: {output_path}")


# Preprocess the dataset
parquet_file = "data/proofwriter_test.parquet"
processed_file = "data/proofwriter_test_processed.json"

print("Preprocessing ProofWriter dataset...")
preprocess_proofwriter(parquet_file, processed_file, max_samples=1000)
print()

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
    cache_dir=f"output/{BACKEND}_programs_proofwriter",
    z3_path="z3",
)

# Create evaluation pipeline with parallel workers
evaluator = EvaluationPipeline(
    proof_of_thought=pot,
    output_dir=f"output/{BACKEND}_evaluation_proofwriter",
    num_workers=10,
)

# Run evaluation on preprocessed dataset
result = evaluator.evaluate(
    dataset=processed_file,
    question_field="question",
    answer_field="answer",
    id_field="id",
    max_samples=100,
    skip_existing=True,
)

# Print results
print("\n" + "=" * 80)
print(f"PROOFWRITER BENCHMARK RESULTS ({BACKEND.upper()} Backend + Azure GPT-5)")
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
print("\nNOTE: ProofWriter includes questions with varying proof depths (QDep).")
print("      'Unknown' answers filtered out for binary classification.")
print("      Dataset: 174k total examples, ~93k with definite True/False answers.")
