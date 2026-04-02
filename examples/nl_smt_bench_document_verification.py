#!/usr/bin/env python3
"""Run staged document verification on NL-SMT-Bench qa_outputs."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from azure_config import get_client_config

from proofofthought.reasoning import ProofOfThought, evaluate_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify NL-SMT-Bench QA pairs with staged SMT2")
    project_root = Path(__file__).resolve().parent.parent
    default_dataset_root = project_root.parent / "NL-SMT-Bench"

    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=default_dataset_root,
        help="Path to the NL-SMT-Bench checkout",
    )
    parser.add_argument(
        "--subset",
        type=Path,
        default=None,
        help="Optional qa_sample JSON file used as a question selector",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "output" / "nl_smt_bench_document_verification",
        help="Directory for document artifacts and aggregate metrics",
    )
    parser.add_argument("--max-docs", type=int, default=None, help="Maximum documents to verify")
    parser.add_argument("--max-pairs", type=int, default=None, help="Maximum QA pairs to verify")
    parser.add_argument("--company", type=str, default=None, help="Filter by company")
    parser.add_argument("--industry", type=str, default=None, help="Filter by industry")
    parser.add_argument("--doc-type", type=str, default=None, help="Filter by doc_type")

    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    args = parse_args()
    dataset_root = args.dataset_root.resolve()
    qa_outputs_dir = dataset_root / "qa_outputs"

    if not qa_outputs_dir.exists():
        raise FileNotFoundError(f"qa_outputs directory not found: {qa_outputs_dir}")

    client_config = get_client_config()
    pot = ProofOfThought(
        llm_client=client_config["llm_client"],
        model=client_config["model"],
    )

    result = evaluate_dataset(
        proof_of_thought=pot,
        dataset_path_or_records=qa_outputs_dir,
        sample_filter=args.subset,
        max_docs=args.max_docs,
        max_pairs=args.max_pairs,
        company=args.company,
        industry=args.industry,
        doc_type=args.doc_type,
        output_dir=args.output_dir,
    )

    metrics = result.metrics
    print("=" * 80)
    print("NL-SMT-BENCH DOCUMENT VERIFICATION")
    print("=" * 80)
    print(f"Documents processed: {metrics.documents_processed}")
    print(f"Documents failed:    {metrics.documents_failed}")
    print(f"Questions verified:  {metrics.total_questions}")
    print(f"Options verified:    {metrics.total_options}")
    print(f"Correct options:     {metrics.correct_options}")
    print(f"Incorrect options:   {metrics.incorrect_options}")
    print(f"Failed options:      {metrics.failed_options}")
    print(f"Accuracy:            {metrics.accuracy:.2%}")
    print(f"Soundness:           {metrics.soundness:.2%}")
    print(f"Unsound supported:   {metrics.unsound_supported_options}")
    print(f"Output dir:          {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
