"""Evaluation pipeline for reasoning datasets."""

import json
import logging
import os
from concurrent.futures import as_completed
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_score,
    recall_score,
)

from z3adapter.reasoning.proof_of_thought import ProofOfThought, QueryResult

logger = logging.getLogger(__name__)


@dataclass
class EvaluationMetrics:
    """Evaluation metrics for reasoning tasks."""

    accuracy: float
    precision: float
    recall: float
    f1_score: float
    specificity: float
    false_positive_rate: float
    false_negative_rate: float
    tp: int
    fp: int
    tn: int
    fn: int
    total_samples: int
    correct_answers: int
    wrong_answers: int
    failed_answers: int


@dataclass
class EvaluationResult:
    """Complete evaluation results."""

    metrics: EvaluationMetrics
    results: list[QueryResult] = field(default_factory=list)
    y_true: list[int] = field(default_factory=list)
    y_pred: list[int] = field(default_factory=list)


class EvaluationPipeline:
    """Dataset-agnostic evaluation pipeline for reasoning tasks."""

    def __init__(
        self,
        proof_of_thought: ProofOfThought,
        output_dir: str = "evaluation_results",
        num_workers: int = 1,
    ) -> None:
        """Initialize evaluation pipeline.

        Args:
            proof_of_thought: ProofOfThought instance
            output_dir: Directory to save evaluation results
            num_workers: Number of parallel workers (default: 1, set to >1 for multiprocessing)
        """
        self.pot = proof_of_thought
        self.output_dir = output_dir
        self.num_workers = num_workers
        os.makedirs(output_dir, exist_ok=True)

    def _process_sample(
        self,
        sample: dict[str, Any],
        idx: int,
        total: int,
        question_field: str,
        answer_field: str,
        id_field: str | None,
        skip_existing: bool,
    ) -> tuple[dict[str, Any], QueryResult | None]:
        """Process a single sample (used for parallel processing).

        Args:
            sample: Sample data
            idx: Sample index
            total: Total number of samples
            question_field: Field name for question
            answer_field: Field name for answer
            id_field: Field name for sample ID
            skip_existing: Whether to skip existing results

        Returns:
            Tuple of (result_data, QueryResult)
        """
        # Extract fields
        question = sample[question_field]
        ground_truth = sample[answer_field]
        sample_id = sample.get(id_field) if id_field else f"sample_{idx}"

        logger.info(f"[{idx+1}/{total}] Processing: {sample_id}")

        # Check if already processed
        result_path = os.path.join(self.output_dir, f"{sample_id}_result.json")
        if skip_existing and os.path.exists(result_path):
            logger.info(f"Skipping {sample_id} (already processed)")
            try:
                with open(result_path) as f:
                    cached = json.load(f)
                    return cached, None
            except Exception as e:
                logger.warning(f"Failed to load cached result: {e}")

        # Query the system (get correct file extension from backend)
        file_ext = self.pot.backend.get_file_extension()
        result = self.pot.query(
            question=question,
            save_program=True,
            program_path=os.path.join(self.output_dir, f"{sample_id}_program{file_ext}"),
        )

        # Create result data
        result_data = {
            "sample_id": sample_id,
            "question": question,
            "ground_truth": ground_truth,
            "answer": result.answer,
            "success": result.success,
            "num_attempts": result.num_attempts,
            "sat_count": result.sat_count,
            "unsat_count": result.unsat_count,
            "error": result.error,
        }

        # Save result
        with open(result_path, "w") as f:
            json.dump(result_data, f, indent=2)

        logger.info(f"Completed {sample_id}: {result.answer} (success={result.success})")

        return result_data, result

    def evaluate(
        self,
        dataset: list[dict[str, Any]] | str,
        question_field: str = "question",
        answer_field: str = "answer",
        id_field: str | None = None,
        max_samples: int | None = None,
        skip_existing: bool = True,
    ) -> EvaluationResult:
        """Evaluate on a dataset.

        Args:
            dataset: List of samples or path to JSON file
            question_field: Field name for question text
            answer_field: Field name for ground truth answer
            id_field: Optional field name for sample ID
            max_samples: Maximum samples to evaluate (None = all)
            skip_existing: Skip samples with existing cached results

        Returns:
            EvaluationResult with metrics and detailed results
        """
        # Load dataset if path provided
        dataset_list: list[dict[str, Any]]
        if isinstance(dataset, str):
            with open(dataset) as f:
                dataset_list = json.load(f)
        else:
            dataset_list = dataset

        # Limit samples if requested
        if max_samples:
            dataset_list = dataset_list[:max_samples]

        logger.info(f"Evaluating {len(dataset_list)} samples with {self.num_workers} workers")

        results = []
        y_true = []
        y_pred = []
        correct = 0
        wrong = 0
        failed = 0

        if self.num_workers == 1:
            # Sequential processing
            for idx, sample in enumerate(dataset_list):
                result_data, result = self._process_sample(
                    sample,
                    idx,
                    len(dataset_list),
                    question_field,
                    answer_field,
                    id_field,
                    skip_existing,
                )

                ground_truth = result_data["ground_truth"]

                # Update metrics from cached or new result
                if result_data.get("success"):
                    y_true.append(int(ground_truth))
                    y_pred.append(int(result_data["answer"]))
                    if result_data["answer"] == ground_truth:
                        correct += 1
                        logger.info("✓ Correct answer")
                    else:
                        wrong += 1
                        logger.info("✗ Wrong answer")
                else:
                    failed += 1
                    logger.warning(f"✗ Failed: {result_data.get('error')}")

                if result:
                    results.append(result)

                # Log current statistics
                total_answered = correct + wrong
                if total_answered > 0:
                    accuracy = correct / total_answered
                    logger.info(
                        f"Current stats: {correct}/{total_answered} correct ({accuracy:.2%})"
                    )
        else:
            # Parallel processing with ProcessPoolExecutor
            # Note: This won't work with the current approach because ProofOfThought can't be pickled
            # We need to use threading instead
            from concurrent.futures import ThreadPoolExecutor

            logger.info("Using parallel processing with threading")

            with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                # Submit all tasks
                futures = {
                    executor.submit(
                        self._process_sample,
                        sample,
                        idx,
                        len(dataset_list),
                        question_field,
                        answer_field,
                        id_field,
                        skip_existing,
                    ): idx
                    for idx, sample in enumerate(dataset_list)
                }

                # Collect results as they complete
                completed = 0
                for future in as_completed(futures):
                    completed += 1
                    try:
                        result_data, result = future.result()
                        ground_truth = result_data["ground_truth"]

                        # Update metrics
                        if result_data.get("success"):
                            y_true.append(int(ground_truth))
                            y_pred.append(int(result_data["answer"]))
                            if result_data["answer"] == ground_truth:
                                correct += 1
                            else:
                                wrong += 1
                        else:
                            failed += 1

                        if result:
                            results.append(result)

                    except Exception as e:
                        logger.error(f"Task failed: {e}")
                        failed += 1

                    # Log progress
                    logger.info(f"Progress: {completed}/{len(dataset_list)} samples completed")
                    total_answered = correct + wrong
                    if total_answered > 0:
                        accuracy = correct / total_answered
                        logger.info(
                            f"Current stats: {correct}/{total_answered} correct ({accuracy:.2%})"
                        )

        # Calculate final metrics
        metrics = self._calculate_metrics(y_true, y_pred, correct, wrong, failed)

        # Log final results
        logger.info("=" * 80)
        logger.info("FINAL EVALUATION RESULTS")
        logger.info("=" * 80)
        logger.info(f"Total samples: {len(dataset_list)}")
        logger.info(f"Correct: {correct}")
        logger.info(f"Wrong: {wrong}")
        logger.info(f"Failed: {failed}")
        logger.info(f"Accuracy: {metrics.accuracy:.2%}")
        logger.info(f"Precision: {metrics.precision:.4f}")
        logger.info(f"Recall: {metrics.recall:.4f}")
        logger.info(f"F1 Score: {metrics.f1_score:.4f}")

        return EvaluationResult(metrics=metrics, results=results, y_true=y_true, y_pred=y_pred)

    def _calculate_metrics(
        self, y_true: list[int], y_pred: list[int], correct: int, wrong: int, failed: int
    ) -> EvaluationMetrics:
        """Calculate evaluation metrics.

        Args:
            y_true: Ground truth labels
            y_pred: Predicted labels
            correct: Number of correct predictions
            wrong: Number of wrong predictions
            failed: Number of failed predictions

        Returns:
            EvaluationMetrics object
        """
        if len(y_true) == 0:
            # No successful predictions
            return EvaluationMetrics(
                accuracy=0.0,
                precision=0.0,
                recall=0.0,
                f1_score=0.0,
                specificity=0.0,
                false_positive_rate=0.0,
                false_negative_rate=0.0,
                tp=0,
                fp=0,
                tn=0,
                fn=0,
                total_samples=correct + wrong + failed,
                correct_answers=correct,
                wrong_answers=wrong,
                failed_answers=failed,
            )

        y_true_arr = np.array(y_true)
        y_pred_arr = np.array(y_pred)

        # Handle edge cases with single class
        if len(np.unique(y_true_arr)) == 1 or len(np.unique(y_pred_arr)) == 1:
            accuracy = accuracy_score(y_true_arr, y_pred_arr)

            if np.array_equal(y_true_arr, y_pred_arr):
                if y_true_arr[0] == 1:  # All positive
                    tp, fp, tn, fn = len(y_true_arr), 0, 0, 0
                else:  # All negative
                    tp, fp, tn, fn = 0, 0, len(y_true_arr), 0
            else:
                if y_true_arr[0] == 1:  # All true positive
                    tp = int(np.sum(y_pred_arr))
                    fn = len(y_true_arr) - tp
                    fp, tn = 0, 0
                else:  # All true negative
                    tn = int(np.sum(~y_pred_arr.astype(bool)))
                    fp = len(y_true_arr) - tn
                    tp, fn = 0, 0

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
            fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
            fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0
        else:
            # Normal case with multiple classes
            cm = confusion_matrix(y_true_arr, y_pred_arr)
            tn, fp, fn, tp = cm.ravel()

            accuracy = accuracy_score(y_true_arr, y_pred_arr)
            precision = precision_score(y_true_arr, y_pred_arr, zero_division=0)
            recall = recall_score(y_true_arr, y_pred_arr, zero_division=0)
            specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
            fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
            fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0

        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        return EvaluationMetrics(
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1,
            specificity=specificity,
            false_positive_rate=fpr,
            false_negative_rate=fnr,
            tp=int(tp),
            fp=int(fp),
            tn=int(tn),
            fn=int(fn),
            total_samples=correct + wrong + failed,
            correct_answers=correct,
            wrong_answers=wrong,
            failed_answers=failed,
        )
