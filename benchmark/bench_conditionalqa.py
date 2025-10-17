#!/usr/bin/env python3
"""Benchmark: ConditionalQA with SMT2 backend and Azure OpenAI.

ConditionalQA is a reading comprehension dataset that requires conditional reasoning
over legal and government documents. Questions include a scenario and ask whether
specific conditions apply based on the document content.

Dataset: ConditionalQA (UK government documents)
Format:
- Documents: 652 UK government web pages with legal/procedural information
- Questions: 2,338 scenario-based questions requiring document reasoning
Structure:
- Each question has: url, scenario, question, answers, evidences
- Documents have: title, url, contents (list of HTML snippets)

Evaluation Strategy: Boolean Question Subset
We focus on boolean (yes/no) questions for clean SMT verification:
- Filter to only questions with "yes"/"no" answers (~60% of dataset)
- Keep original Q&A format (minimal preprocessing)
- Direct SAT/UNSAT evaluation matches boolean answers
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Literal

# Add parent directory to path for z3adapter imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.azure_config import get_client_config
from z3adapter.reasoning import EvaluationPipeline, ProofOfThought

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def clean_html_content(html_list: list[str]) -> str:
    """Convert list of HTML snippets to clean text for reasoning.

    Args:
        html_list: List of HTML content strings

    Returns:
        Clean text with basic structure preserved
    """
    import re

    text_parts = []
    for html in html_list:
        # Remove HTML tags but preserve structure
        text = re.sub(r"<h[1-6]>", "\n## ", html)
        text = re.sub(r"</h[1-6]>", "\n", text)
        text = re.sub(r"<p>", "\n", text)
        text = re.sub(r"</p>", "\n", text)
        text = re.sub(r"<li>", "\n- ", text)
        text = re.sub(r"</li>", "", text)
        text = re.sub(r"<tr>", "\n| ", text)
        text = re.sub(r"</tr>", " |", text)
        text = re.sub(r"<[^>]+>", "", text)

        # Clean up whitespace
        text = re.sub(r"\n\s*\n\s*\n", "\n\n", text)
        text = text.strip()

        if text:
            text_parts.append(text)

    return "\n\n".join(text_parts)


def preprocess_documents(documents_path: str, output_path: str) -> dict[str, dict[str, Any]]:
    """Preprocess ConditionalQA documents for reasoning.

    Args:
        documents_path: Path to conditionalqa_documents.json
        output_path: Path to save preprocessed documents

    Returns:
        Dictionary mapping URL to processed document data
    """
    with open(documents_path) as f:
        documents = json.load(f)

    print(f"Total documents: {len(documents)}")

    processed_docs = {}
    for doc in documents:
        url = doc["url"]
        title = doc["title"]
        contents_text = clean_html_content(doc["contents"])

        processed_docs[url] = {
            "url": url,
            "title": title,
            "content": contents_text,
            "original_contents": doc["contents"],
        }

    with open(output_path, "w") as f:
        json.dump(processed_docs, f, indent=2)

    print(f"Preprocessed {len(processed_docs)} documents")
    print(f"Saved to: {output_path}")

    return processed_docs


def preprocess_questions(
    questions_path: str,
    documents: dict[str, dict[str, Any]],
    output_path: str,
    max_samples: int | None = None,
) -> list[dict[str, Any]]:
    """Preprocess ConditionalQA questions for evaluation.

    ConditionalQA format:
    - url: Link to source document
    - scenario: User's situation/context
    - question: Specific question about the scenario
    - not_answerable: Whether question can be answered from document
    - answers: List of [answer_text, supporting_facts]
    - evidences: List of HTML snippets supporting the answer

    Output format:
    - id: Original question ID
    - question: scenario + question + document content (MINIMAL CHANGES)
    - answer: Boolean (True/False) for yes/no answers only
    - url: Document URL
    - answerable: Whether question is answerable

    Note: Only includes questions with boolean yes/no answers.
    """
    with open(questions_path) as f:
        questions = json.load(f)

    print(f"Total questions: {len(questions)}")

    processed = []
    answerable_count = 0
    not_answerable_count = 0
    skipped_non_boolean = 0

    for q in questions:
        url = q["url"]

        # Get associated document
        if url not in documents:
            print(f"Warning: No document found for URL {url}")
            continue

        doc = documents[url]

        # Parse answer - ConditionalQA answers are [answer_text, supporting_facts]
        answer_text = q["answers"][0][0] if q["answers"] else None
        if not answer_text:
            continue

        # Convert to boolean (filter to boolean-only)
        answer_lower = answer_text.lower().strip()
        if answer_lower in ["yes", "true"]:
            answer_bool = True
        elif answer_lower in ["no", "false"]:
            answer_bool = False
        else:
            # Skip non-boolean answers
            skipped_non_boolean += 1
            continue

        # Combine scenario, question, and document (MINIMAL - no transformation)
        full_question = (
            f"Scenario: {q['scenario']}\n\n"
            f"Question: {q['question']}\n\n"
            f"Document - {doc['title']}:\n{doc['content']}"
        )

        is_answerable = not q.get("not_answerable", False)
        if is_answerable:
            answerable_count += 1
        else:
            not_answerable_count += 1

        processed.append(
            {
                "id": q["id"],
                "question": full_question,
                "answer": answer_bool,
                "answer_text": answer_text,
                "url": url,
                "answerable": is_answerable,
                "scenario": q["scenario"],
                "original_question": q["question"],
            }
        )

        if max_samples and len(processed) >= max_samples:
            break

    with open(output_path, "w") as f:
        json.dump(processed, f, indent=2)

    print(f"Preprocessed {len(processed)} questions (boolean answers only)")
    print(f"  - Answerable: {answerable_count}, Not answerable: {not_answerable_count}")
    print(f"  - Skipped non-boolean: {skipped_non_boolean}")
    print(f"Saved to: {output_path}")

    return processed


def main() -> None:
    """Run ConditionalQA benchmark."""
    # Preprocess documents
    documents_file = "data/conditionalqa_documents.json"
    processed_docs_file = "data/conditionalqa_documents_processed.json"

    print("=" * 80)
    print("STAGE 1: PREPROCESSING DOCUMENTS")
    print("=" * 80)

    if os.path.exists(processed_docs_file):
        print(f"Loading preprocessed documents from {processed_docs_file}")
        with open(processed_docs_file) as f:
            processed_docs = json.load(f)
    else:
        print("Preprocessing ConditionalQA documents...")
        processed_docs = preprocess_documents(documents_file, processed_docs_file)

    print()

    # Preprocess questions
    questions_file = "data/conditionalqa_train.json"
    processed_questions_file = "data/conditionalqa_train_processed.json"

    print("=" * 80)
    print("STAGE 2: PREPROCESSING QUESTIONS")
    print("=" * 80)

    if os.path.exists(processed_questions_file):
        print(f"Loading preprocessed questions from {processed_questions_file}")
    else:
        print("Preprocessing ConditionalQA questions...")
        preprocess_questions(questions_file, processed_docs, processed_questions_file)

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
        cache_dir=f"output/{BACKEND}_programs_conditionalqa",
        z3_path="z3",
    )

    # Run evaluation
    print("=" * 80)
    print("STAGE 3: EVALUATING QUESTIONS")
    print("=" * 80)

    # Create evaluation pipeline with parallel workers
    evaluator = EvaluationPipeline(
        proof_of_thought=pot,
        output_dir=f"output/{BACKEND}_evaluation_conditionalqa",
        num_workers=10,
    )

    # Run evaluation on preprocessed questions
    result = evaluator.evaluate(
        dataset=processed_questions_file,
        question_field="question",
        answer_field="answer",
        id_field="id",
        max_samples=100,
        skip_existing=True,
    )

    # Print results
    print("\n" + "=" * 80)
    print(f"CONDITIONALQA BENCHMARK RESULTS ({BACKEND.upper()} Backend + Azure GPT-5)")
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
    print("\nNOTE: ConditionalQA benchmark uses boolean question subset.")
    print("      Dataset: 652 documents, filtered to ~60% with yes/no answers.")
    print("      Original Q&A format preserved (minimal preprocessing).")
    print("=" * 80)


if __name__ == "__main__":
    main()
