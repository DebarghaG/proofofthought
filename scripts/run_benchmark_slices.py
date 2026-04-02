"""Run benchmark slices on the current staged SMT-LIB pipeline."""

from __future__ import annotations

import json
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = Path("/tmp/pot-benchmark-slices-current")
OUTPUT_ROOT = DEFAULT_OUTPUT_ROOT
sys.path.insert(0, str(ROOT))

from utils.azure_config import get_client_config
from z3adapter.reasoning import EvaluationPipeline, ProofOfThought


def _load_json(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def _proofwriter_dataset(max_samples: int) -> list[dict]:
    items = _load_json(ROOT / "data/proofwriter_test_processed.json")
    return items[:max_samples]


def _prontoqa_dataset(max_samples: int) -> list[dict]:
    items = _load_json(ROOT / "data/ProntoQA_dev_processed.json")
    return items[:max_samples]


def _folio_dataset(max_samples: int) -> list[dict]:
    items = _load_json(ROOT / "data/folio_v2_train_processed.json")
    return items[:max_samples]


def _strategyqa_dataset(max_samples: int) -> list[dict]:
    items = _load_json(ROOT / "data/strategyQA_train.json")
    return items[:max_samples]


DATASETS = [
    {
        "name": "proofwriter",
        "loader": _proofwriter_dataset,
        "text_field": "original_theory",
        "question_field": "original_question",
        "answer_field": "answer",
        "id_field": "id",
    },
    {
        "name": "prontoqa",
        "loader": _prontoqa_dataset,
        "text_field": "original_context",
        "question_field": "original_question",
        "answer_field": "answer",
        "id_field": "id",
    },
    {
        "name": "folio",
        "loader": _folio_dataset,
        "text_field": "original_premises",
        "question_field": "original_conclusion",
        "answer_field": "answer",
        "id_field": "id",
    },
    {
        "name": "strategyqa",
        "loader": _strategyqa_dataset,
        "text_field": None,
        "question_field": "question",
        "answer_field": "answer",
        "id_field": "qid",
    },
]


def run_dataset(
    config: dict,
    client_config: dict,
    *,
    max_samples: int,
    num_workers: int,
    allow_background_knowledge: bool,
) -> dict:
    dataset_name = config["name"]
    dataset = config["loader"](max_samples)
    dataset_output = OUTPUT_ROOT / dataset_name
    dataset_output.mkdir(parents=True, exist_ok=True)

    pot = ProofOfThought(
        llm_client=client_config["llm_client"],
        model=client_config["model"],
        backend="staged_smt2",
        verification_mode="entailment",
        max_attempts=3,
        max_stage_repairs=1,
        max_solver_repairs=1,
        allow_background_knowledge=allow_background_knowledge,
        cache_dir=str(dataset_output / "program_cache"),
        z3_path="z3",
    )

    evaluator = EvaluationPipeline(
        proof_of_thought=pot,
        output_dir=str(dataset_output / "evaluation"),
        num_workers=num_workers,
    )

    start = time.perf_counter()
    result = evaluator.evaluate(
        dataset=dataset,
        text_field=config["text_field"],
        question_field=config["question_field"],
        answer_field=config["answer_field"],
        id_field=config["id_field"],
        skip_existing=False,
    )
    elapsed = time.perf_counter() - start

    metrics = result.metrics
    evaluation_dir = dataset_output / "evaluation"
    background_informed = 0
    strict_grounded = 0
    for result_path in evaluation_dir.glob("*_result.json"):
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if payload.get("rigor_level") == "background_informed":
            background_informed += 1
        else:
            strict_grounded += 1
    summary = {
        "dataset": dataset_name,
        "samples": metrics.total_samples,
        "correct": metrics.correct_answers,
        "wrong": metrics.wrong_answers,
        "failed": metrics.failed_answers,
        "accuracy": metrics.accuracy,
        "precision": metrics.precision,
        "recall": metrics.recall,
        "f1": metrics.f1_score,
        "specificity": metrics.specificity,
        "elapsed_seconds": elapsed,
        "background_informed": background_informed,
        "strict_grounded": strict_grounded,
        "allow_background_knowledge": allow_background_knowledge,
    }

    with (dataset_output / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=[dataset["name"] for dataset in DATASETS],
        help="Subset of datasets to run",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Directory for benchmark outputs",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=10,
        help="Number of samples to run per dataset",
    )
    parser.add_argument(
        "--num-workers",
        type=int,
        default=5,
        help="Parallel workers per dataset",
    )
    parser.add_argument(
        "--allow-background-knowledge",
        action="store_true",
        help="Allow explicitly tagged common-knowledge assertions when strict grounding is insufficient",
    )
    args = parser.parse_args()

    global OUTPUT_ROOT
    OUTPUT_ROOT = Path(args.output_root)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    client_config = get_client_config()

    selected = DATASETS
    if args.datasets:
        selected_names = set(args.datasets)
        selected = [dataset for dataset in DATASETS if dataset["name"] in selected_names]

    summaries = [
        run_dataset(
            dataset_config,
            client_config,
            max_samples=args.max_samples,
            num_workers=args.num_workers,
            allow_background_knowledge=args.allow_background_knowledge,
        )
        for dataset_config in selected
    ]

    with (OUTPUT_ROOT / "all_summaries.json").open("w", encoding="utf-8") as handle:
        json.dump(summaries, handle, indent=2)

    for summary in summaries:
        print(
            f"{summary['dataset']}: "
            f"{summary['correct']}/{summary['samples']} correct, "
            f"{summary['wrong']} wrong, {summary['failed']} failed, "
            f"background_informed={summary['background_informed']}, "
            f"accuracy={summary['accuracy']:.2%}, "
            f"elapsed={summary['elapsed_seconds']:.1f}s"
        )


if __name__ == "__main__":
    main()
