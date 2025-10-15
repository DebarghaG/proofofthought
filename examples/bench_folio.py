#!/usr/bin/env python3
"""Benchmark: FOLIO with SMT2 backend and Azure OpenAI.

FOLIO (First-Order Logic in Natural Language) is a human-annotated dataset
for evaluating natural language reasoning with first-order logic. It contains
logically complex and diverse examples with formal FOL annotations verified
by an FOL inference engine.

Dataset: HuggingFace yale-nlp/FOLIO (train split)
Format: JSONL file with premises, conclusion, and label (True/False/Uncertain)
Note: This script filters out "Uncertain" labels for binary classification
"""

import json
import logging
import sys
from pathlib import Path

# Add parent directory to path for z3dsl imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from azure_config import get_client_config

from z3dsl.reasoning import EvaluationPipeline, ProofOfThought

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def preprocess_folio(jsonl_path: str, output_path: str) -> None:
    """Preprocess FOLIO to combine premises + conclusion and filter Uncertain labels.

    FOLIO format:
    - premises: Background context (natural language statements)
    - conclusion: The statement to verify
    - label: "True", "False", or "Uncertain"
    - story_id: ID of the premise set
    - example_id: Unique example ID

    Output format:
    - question: premises + "\n\nConclusion: " + conclusion
    - answer: True/False (boolean, "Uncertain" samples filtered out)
    - id: example_id
    - story_id: original story_id
    """
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
        # Combine premises with conclusion for complete reasoning scenario
        # Frame as direct assertion task to match SAT=True/UNSAT=False interpretation
        # Instead of asking "does it follow?", ask "is it true given the premises?"
        full_question = f"Given the following premises:\n\n{item['premises']}\n\nAssuming all premises are true, is the following statement true or false?\n\nStatement: {item['conclusion']}"

        # Convert string label to boolean
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
jsonl_file = "examples/folio_v2_train.jsonl"
processed_file = "examples/folio_v2_train_processed.json"

print("Preprocessing FOLIO dataset...")
preprocess_folio(jsonl_file, processed_file)
print()

# Get Azure OpenAI configuration
config = get_client_config()

# Create ProofOfThought instance with SMT2 backend
pot = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="smt2",
    max_attempts=3,
    cache_dir="output/programs_smt2_folio",
    z3_path="z3",
)

# Create evaluation pipeline with parallel workers
evaluator = EvaluationPipeline(
    proof_of_thought=pot,
    output_dir="output/evaluation_results_folio",
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
print("FOLIO BENCHMARK RESULTS (SMT2 Backend + Azure GPT-5)")
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
print("\nNOTE: FOLIO is a challenging dataset with complex first-order logic reasoning.")
print("      It includes expert-written examples with formal FOL annotations.")
print("      'Uncertain' labels filtered out for binary classification.")
print("      Dataset: 1,001 total examples, 677 with definite True/False labels.")
