#!/usr/bin/env python3
"""Benchmark: ProntoQA with SMT2 backend and Azure OpenAI.

ProntoQA is a synthetic question-answering dataset designed to formally analyze
chain-of-thought reasoning in large language models. It requires deductive reasoning
(modus ponens) to answer true/false queries with varying reasoning depths (hops).

Dataset: HuggingFace renma/ProntoQA
Format: Each entry contains context (facts/rules), question, and answer ("A"=True, "B"=False)
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


def preprocess_prontoqa(input_path: str, output_path: str) -> None:
    """Preprocess ProntoQA to combine context + question and convert answer format.

    ProntoQA format:
    - context: Background facts and rules
    - question: "Is the following statement true or false? [statement]"
    - answer: "A" (True) or "B" (False)

    Output format:
    - question: context + "\n\n" + question
    - answer: True/False (boolean)
    - id: original id
    """
    with open(input_path) as f:
        data = json.load(f)

    processed = []
    for item in data:
        # Combine context with question for complete reasoning scenario
        full_question = f"{item['context']}\n\n{item['question']}"

        # Convert A/B answer to boolean (A=True, B=False)
        answer_bool = True if item["answer"] == "A" else False

        processed.append(
            {
                "id": item["id"],
                "question": full_question,
                "answer": answer_bool,
                "original_context": item["context"],
                "original_question": item["question"],
            }
        )

    with open(output_path, "w") as f:
        json.dump(processed, f, indent=2)

    print(f"Preprocessed {len(processed)} ProntoQA examples")
    print(f"Saved to: {output_path}")


# Preprocess the dataset
input_file = "examples/ProntoQA_dev_gpt-4.json"
processed_file = "examples/ProntoQA_dev_processed.json"

print("Preprocessing ProntoQA dataset...")
preprocess_prontoqa(input_file, processed_file)
print()

# Get Azure OpenAI configuration
config = get_client_config()

# Create ProofOfThought instance with SMT2 backend
pot = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="smt2",
    max_attempts=3,
    cache_dir="output/programs_smt2_prontoqa",
    z3_path="z3",
)

# Create evaluation pipeline with parallel workers
evaluator = EvaluationPipeline(
    proof_of_thought=pot,
    output_dir="output/evaluation_results_prontoqa",
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
print("PRONTOQA BENCHMARK RESULTS (SMT2 Backend + Azure GPT-5)")
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
print("\nNOTE: ProntoQA tests deductive reasoning with varying depths.")
print("      Dataset contains 500 synthetic examples with formal logic rules.")
