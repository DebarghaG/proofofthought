"""Reasoning components for proof-of-thought using Z3."""

from z3adapter.reasoning.document_verification import (
    DatasetEvaluationMetrics,
    DatasetEvaluationResult,
    DocumentChunkRecord,
    DocumentModel,
    DocumentVerificationMetrics,
    DocumentVerificationPipeline,
    DocumentVerificationResult,
    OptionVerificationResult,
    QuestionVerificationResult,
    build_document_model,
    evaluate_dataset,
    load_question_selector,
    verify_qa_pairs,
)
from z3adapter.reasoning.evaluation import EvaluationMetrics, EvaluationPipeline, EvaluationResult
from z3adapter.reasoning.proof_of_thought import ProofOfThought, QueryResult
from z3adapter.reasoning.staged_artifact import (
    ArtifactCheck,
    ArtifactExecution,
    ArtifactTraceEntry,
    STAGE_ORDER,
    StagedArtifact,
)

__all__ = [
    "DocumentChunkRecord",
    "DocumentModel",
    "OptionVerificationResult",
    "QuestionVerificationResult",
    "DocumentVerificationMetrics",
    "DocumentVerificationResult",
    "DatasetEvaluationMetrics",
    "DatasetEvaluationResult",
    "DocumentVerificationPipeline",
    "build_document_model",
    "verify_qa_pairs",
    "evaluate_dataset",
    "load_question_selector",
    "ProofOfThought",
    "QueryResult",
    "StagedArtifact",
    "ArtifactExecution",
    "ArtifactTraceEntry",
    "ArtifactCheck",
    "STAGE_ORDER",
    "EvaluationPipeline",
    "EvaluationResult",
    "EvaluationMetrics",
]
