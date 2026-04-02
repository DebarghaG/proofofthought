"""Document-grounded staged verification pipeline."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from z3adapter.backends.abstract import VerificationResult
from z3adapter.backends.smt2 import StagedGenerator
from z3adapter.backends.smt2.backend import StagedSMT2Backend
from z3adapter.backends.smt2.ir import ConversionContext, SMTAssertion, SMTConstant, SMTSortKind
from z3adapter.reasoning.proof_of_thought import ProofOfThought

logger = logging.getLogger(__name__)

OptionType = Literal["valid", "invalid", "ambiguous"]
OptionClaimKind = Literal["claim", "underdetermined", "unknown"]
VerificationStatus = Literal["supported", "contradicted", "unresolved", "error"]
QuestionKey = tuple[str, str, str, str]

FOUNDATION_STAGES = ["sorts", "functions", "constants", "knowledge_base"]
EXPECTED_STATUS_BY_OPTION: dict[OptionType, VerificationStatus] = {
    "valid": "supported",
    "invalid": "contradicted",
    "ambiguous": "supported",
}

QUESTION_SCENARIO_PROMPT = """You translate a document question into SMT-LIB scenario setup.

TASK: QUESTION_SCENARIO

Return only SMT-LIB `declare-const` and `assert` commands needed to encode the
specific factual situation described in the question.

Rules:
- Use only sorts, functions, and enum values already available in the provided foundation.
- Introduce fresh scenario-specific constants when needed.
- Do not emit `(check-sat)`, `(get-model)`, `(push ...)`, `(pop ...)`, comments, or prose.
- If the question does not require extra scenario facts, output exactly `NONE`.

<document_metadata>
{metadata}
</document_metadata>

<context_summary>
{context_summary}
</context_summary>

<source_chunk>
{chunk_text}
</source_chunk>

<foundation_smt2>
{foundation_smt2}
</foundation_smt2>

<question>
{question}
</question>
"""

OPTION_CLAIM_PROMPT = """You translate one answer option into a structured SMT verification target.

TASK: OPTION_CLAIM

Return valid JSON with this schema:
{{
  "kind": "claim" | "underdetermined" | "unknown",
  "proposition": "<closed SMT-LIB boolean expression or null>"
}}

Rules:
- `kind="claim"` means the answer asserts the proposition is true.
- `kind="underdetermined"` means the answer asserts the proposition is not settled by the document.
- `kind="unknown"` means you cannot express the answer faithfully with the available symbols.
- `proposition` must be a closed SMT-LIB boolean expression.
- When `kind="underdetermined"`, `proposition` must still be the concrete proposition
  that the answer says the document does not settle.
- Use only symbols from the foundation or the scenario setup.
- Do not emit `(assert ...)`, `(check-sat)`, comments, or markdown in `proposition`.

<question>
{question}
</question>

<scenario_setup>
{scenario_setup}
</scenario_setup>

<answer_option>
{answer_text}
</answer_option>

<foundation_smt2>
{foundation_smt2}
</foundation_smt2>
"""


@dataclass
class DocumentChunkRecord:
    """Chunk-level staged modeling artifact."""

    chunk_index: int
    sentence_start: int | None
    sentence_end: int | None
    num_sentences: int | None
    text: str
    qa_pairs: list[dict[str, Any]] = field(default_factory=list)
    stage_outputs: dict[str, str] = field(default_factory=dict)
    context_summary: str = ""
    fragment_smt2: str = ""


@dataclass
class DocumentModel:
    """Formalized document and staged artifacts."""

    metadata: dict[str, Any]
    document_text: str
    chunks: list[DocumentChunkRecord] = field(default_factory=list)
    context_summary: str = ""
    foundation_smt2: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    source_path: str | None = None


@dataclass
class OptionVerificationResult:
    """Verification outcome for one answer option."""

    option_type: OptionType
    question: str
    answer_text: str
    chunk_index: int
    claim_kind: OptionClaimKind
    proposition_smt2: str | None
    status: VerificationStatus
    expected_status: VerificationStatus
    is_correct: bool
    error: str | None = None


@dataclass
class QuestionVerificationResult:
    """Verification outcome for one QA pair."""

    question: str
    chunk_index: int
    chunk_text: str
    question_type: str = ""
    difficulty: str = ""
    tags: list[str] = field(default_factory=list)
    scenario_smt2: str = ""
    question_status: VerificationStatus = "error"
    support_check: str = "n/a"
    contradiction_check: str = "n/a"
    options: list[OptionVerificationResult] = field(default_factory=list)
    error: str | None = None


@dataclass
class StructuredOptionClaim:
    """Structured SMT claim extracted from one answer option."""

    kind: OptionClaimKind
    proposition: str | None


@dataclass
class DocumentVerificationMetrics:
    """Aggregate metrics for a single document."""

    total_questions: int
    total_options: int
    correct_options: int
    incorrect_options: int
    failed_options: int
    supported_options: int
    unsound_supported_options: int
    contradicted_options: int
    unresolved_options: int
    accuracy: float
    soundness: float


@dataclass
class DocumentVerificationResult:
    """Verification outcome for one document."""

    metadata: dict[str, Any]
    source_path: str | None
    question_results: list[QuestionVerificationResult] = field(default_factory=list)
    metrics: DocumentVerificationMetrics | None = None


@dataclass
class DatasetEvaluationMetrics:
    """Aggregate metrics for a dataset run."""

    documents_processed: int
    documents_failed: int
    total_questions: int
    total_options: int
    correct_options: int
    incorrect_options: int
    failed_options: int
    supported_options: int
    unsound_supported_options: int
    contradicted_options: int
    unresolved_options: int
    accuracy: float
    soundness: float


@dataclass
class DatasetEvaluationResult:
    """Full dataset evaluation output."""

    metrics: DatasetEvaluationMetrics
    documents: list[DocumentVerificationResult] = field(default_factory=list)


class PromptCompletionAdapter:
    """Adapter that exposes a simple prompt -> text interface."""

    def __init__(
        self,
        llm_client: Any,
        model: str,
        max_completion_tokens: int = 4096,
    ) -> None:
        self.llm_client = llm_client
        self.model = model
        self.max_completion_tokens = max_completion_tokens

    def generate(self, prompt: str, response_format: dict[str, str] | None = None) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": self.max_completion_tokens,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format

        response = self.llm_client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        return content or ""

    def generate_json(self, prompt: str) -> dict[str, Any]:
        raw_output = self.generate(prompt, response_format={"type": "json_object"})
        return json.loads(raw_output)


class DocumentVerificationPipeline:
    """Build staged document models and verify QA pairs against them."""

    def __init__(
        self,
        proof_of_thought: ProofOfThought,
        output_dir: str | Path | None = None,
    ) -> None:
        if not isinstance(proof_of_thought.backend, StagedSMT2Backend):
            raise TypeError(
                "DocumentVerificationPipeline requires the staged SMT-LIB backend. "
                "Use ProofOfThought() or ProofOfThought(..., backend='staged_smt2')."
            )

        self.pot = proof_of_thought
        self.backend = proof_of_thought.backend
        self.prompt_client = PromptCompletionAdapter(
            llm_client=proof_of_thought.llm_client,
            model=proof_of_thought.model,
        )
        self.output_dir = Path(output_dir) if output_dir else None
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_document_model(
        self,
        document_text: str,
        chunks: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
        source_path: str | None = None,
    ) -> DocumentModel:
        """Build a staged SMT foundation for a document using ordered chunks."""
        document_metadata = dict(metadata or {})
        document_key = self._document_slug(document_metadata)
        normalized_chunks = [self._normalize_chunk(chunk) for chunk in chunks]
        clean_text = self._strip_front_matter(document_text).strip()
        if not clean_text:
            clean_text = "\n\n".join(chunk["text"] for chunk in normalized_chunks).strip()

        generator = StagedGenerator(self.prompt_client)
        chunk_records: list[DocumentChunkRecord] = []
        total_chunks = len(normalized_chunks)
        total_qa_pairs = sum(len(chunk.get("qa_pairs", [])) for chunk in normalized_chunks)
        logger.info(
            "Building document model for %s: chunks=%d qa_pairs=%d",
            document_key,
            total_chunks,
            total_qa_pairs,
        )

        for chunk_index, chunk in enumerate(normalized_chunks):
            logger.info(
                "Document %s: building chunk %d/%d (chunk_index=%s, words=%d, qa_pairs=%d)",
                document_key,
                chunk_index + 1,
                total_chunks,
                chunk["chunk_index"],
                len(chunk["text"].split()),
                len(chunk.get("qa_pairs", [])),
            )
            result = generator.generate(
                text=chunk["text"],
                question="",
                stages=FOUNDATION_STAGES,
                reset_context=chunk_index == 0,
            )
            if result.errors:
                raise RuntimeError(
                    f"Chunk {chunk['chunk_index']} staged generation failed: {'; '.join(result.errors)}"
                )

            chunk_records.append(
                DocumentChunkRecord(
                    chunk_index=chunk["chunk_index"],
                    sentence_start=chunk.get("sentence_start"),
                    sentence_end=chunk.get("sentence_end"),
                    num_sentences=chunk.get("num_sentences"),
                    text=chunk["text"],
                    qa_pairs=list(chunk.get("qa_pairs", [])),
                    stage_outputs=dict(result.stage_outputs),
                    context_summary=result.context.to_summary(),
                    fragment_smt2=self._compose_stage_fragment(result.stage_outputs),
                )
            )
            logger.info(
                "Document %s: finished chunk %d/%d",
                document_key,
                chunk_index + 1,
                total_chunks,
            )

        context = generator.get_context()
        self._enrich_document_context(context, normalized_chunks)
        foundation_smt2 = generator.compose_context_program(
            include_scenario=False,
            include_queries=False,
        )
        logger.info(
            "Completed document model for %s: sorts=%d functions=%d constants=%d kb_assertions=%d",
            document_key,
            len(context.sorts),
            len(context.functions),
            len(context.constants),
            len(context.kb_assertions),
        )

        return DocumentModel(
            metadata=document_metadata,
            document_text=clean_text,
            chunks=chunk_records,
            context_summary=context.to_summary(),
            foundation_smt2=foundation_smt2,
            context=context.to_dict(),
            source_path=source_path,
        )

    def verify_qa_pairs(
        self,
        document_model: DocumentModel,
        qa_pairs: list[dict[str, Any]] | None = None,
    ) -> DocumentVerificationResult:
        """Verify QA pairs against a built document model."""
        document_key = self._document_slug(document_model.metadata)
        qa_items = qa_pairs or self._flatten_qa_pairs(document_model)
        question_results: list[QuestionVerificationResult] = []
        total_questions = len(qa_items)
        logger.info("Verifying QA pairs for %s: questions=%d", document_key, total_questions)

        for question_index, qa_item in enumerate(qa_items, start=1):
            qa_pair = qa_item["qa_pair"]
            question = qa_pair["question"]
            chunk_index = qa_item["chunk_index"]
            chunk_text = qa_item["chunk_text"]
            logger.info(
                "Document %s: verifying question %d/%d (chunk=%d) %s",
                document_key,
                question_index,
                total_questions,
                chunk_index,
                self._summarize_question(question),
            )
            scenario_smt2 = self._generate_question_scenario(
                document_model=document_model,
                question=question,
                chunk_text=chunk_text,
            )
            base_program = self._build_base_program(
                foundation_smt2=document_model.foundation_smt2,
                scenario_smt2=scenario_smt2,
            )

            options: list[OptionVerificationResult] = []
            answers = qa_pair.get("answers", {})
            for option_type in ("valid", "invalid", "ambiguous"):
                answer_text = answers.get(option_type)
                if answer_text is None:
                    continue

                structured_claim = self._extract_option_claim(
                    document_model=document_model,
                    question=question,
                    answer_text=answer_text,
                    scenario_smt2=scenario_smt2,
                )
                expected_status = EXPECTED_STATUS_BY_OPTION[option_type]
                proposition = structured_claim.proposition

                if structured_claim.kind == "unknown" or proposition is None:
                    options.append(
                        OptionVerificationResult(
                            option_type=option_type,
                            question=question,
                            answer_text=answer_text,
                            chunk_index=chunk_index,
                            claim_kind=structured_claim.kind,
                            proposition_smt2=proposition,
                            status="error",
                            expected_status=expected_status,
                            is_correct=False,
                            error="Failed to derive a structured SMT claim for the answer option.",
                        )
                    )
                    continue

                support_result = self._run_solver_check(base_program, proposition)
                contradiction_result = self._run_solver_check(base_program, f"(not {proposition})")
                proposition_status = self._classify_proposition_status(
                    support_result=support_result,
                    contradiction_result=contradiction_result,
                )
                option_status = self._classify_option_from_claim_kind(
                    proposition_status=proposition_status,
                    claim_kind=structured_claim.kind,
                )
                option_error = self._question_error(support_result, contradiction_result)

                options.append(
                    OptionVerificationResult(
                        option_type=option_type,
                        question=question,
                        answer_text=answer_text,
                        chunk_index=chunk_index,
                        claim_kind=structured_claim.kind,
                        proposition_smt2=proposition,
                        status=option_status,
                        expected_status=expected_status,
                        is_correct=option_status == expected_status,
                        error=option_error,
                    )
                )

            question_status = self._derive_question_status(options)
            logger.info(
                "Document %s: finished question %d/%d -> %s",
                document_key,
                question_index,
                total_questions,
                ", ".join(f"{option.option_type}={option.status}" for option in options)
                or "no_options",
            )

            question_results.append(
                QuestionVerificationResult(
                    question=question,
                    chunk_index=chunk_index,
                    chunk_text=chunk_text,
                    question_type=qa_pair.get("question_type", ""),
                    difficulty=qa_pair.get("difficulty", ""),
                    tags=list(qa_pair.get("tags", [])),
                    scenario_smt2=scenario_smt2,
                    question_status=question_status,
                    support_check="per_option",
                    contradiction_check="per_option",
                    options=options,
                    error=self._aggregate_option_errors(options),
                )
            )

        return DocumentVerificationResult(
            metadata=dict(document_model.metadata),
            source_path=document_model.source_path,
            question_results=question_results,
            metrics=self._calculate_document_metrics(question_results),
        )

    def evaluate_dataset(
        self,
        dataset_path_or_records: str | Path | list[dict[str, Any]],
        sample_filter: str | Path | set[QuestionKey] | None = None,
        max_docs: int | None = None,
        max_pairs: int | None = None,
        company: str | None = None,
        industry: str | None = None,
        doc_type: str | None = None,
    ) -> DatasetEvaluationResult:
        """Evaluate NL-SMT-Bench-style qa_outputs using staged document verification."""
        selector = self._load_question_selector(sample_filter)
        records = self._load_dataset_records(
            dataset_path_or_records=dataset_path_or_records,
            selector=selector,
            max_docs=max_docs,
            max_pairs=max_pairs,
            company=company,
            industry=industry,
            doc_type=doc_type,
        )

        document_results: list[DocumentVerificationResult] = []
        documents_failed = 0
        total_documents = len(records)
        logger.info("Loaded %d documents for dataset evaluation", total_documents)

        for document_index, record in enumerate(records, start=1):
            metadata = dict(record["metadata"])
            document_key = self._document_slug(metadata)
            logger.info(
                "[%d/%d] Starting document %s: chunks=%d qa_pairs=%d",
                document_index,
                total_documents,
                document_key,
                len(record["chunks"]),
                len(record["qa_items"]),
            )
            try:
                model = self.build_document_model(
                    document_text=record["document_text"],
                    chunks=record["chunks"],
                    metadata=metadata,
                    source_path=record.get("source_path"),
                )
                result = self.verify_qa_pairs(model, qa_pairs=record["qa_items"])
                document_results.append(result)
                self._persist_document_artifacts(model, result)
                if result.metrics is not None:
                    logger.info(
                        "[%d/%d] Finished document %s: questions=%d options=%d correct=%d incorrect=%d failed=%d accuracy=%.2f%% soundness=%.2f%% unsound_supported=%d",
                        document_index,
                        total_documents,
                        document_key,
                        result.metrics.total_questions,
                        result.metrics.total_options,
                        result.metrics.correct_options,
                        result.metrics.incorrect_options,
                        result.metrics.failed_options,
                        result.metrics.accuracy * 100,
                        result.metrics.soundness * 100,
                        result.metrics.unsound_supported_options,
                    )
            except Exception as exc:
                documents_failed += 1
                logger.exception(
                    "Document verification failed for %s/%s/%s",
                    metadata.get("industry"),
                    metadata.get("company"),
                    metadata.get("doc_type"),
                )
                self._persist_document_error(metadata, record.get("source_path"), exc)

        metrics = self._calculate_dataset_metrics(document_results, documents_failed)
        dataset_result = DatasetEvaluationResult(metrics=metrics, documents=document_results)
        self._persist_dataset_metrics(dataset_result)
        return dataset_result

    def _generate_question_scenario(
        self,
        document_model: DocumentModel,
        question: str,
        chunk_text: str,
    ) -> str:
        metadata = json.dumps(document_model.metadata, indent=2, sort_keys=True)
        prompt = QUESTION_SCENARIO_PROMPT.format(
            metadata=metadata,
            context_summary=document_model.context_summary,
            chunk_text=chunk_text,
            foundation_smt2=document_model.foundation_smt2,
            question=question,
        )
        raw_output = self.prompt_client.generate(prompt)
        scenario_setup = self._extract_scenario_setup(raw_output)
        return self._sanitize_scenario_setup(scenario_setup, document_model.context)

    def _extract_option_claim(
        self,
        document_model: DocumentModel,
        question: str,
        answer_text: str,
        scenario_smt2: str,
    ) -> StructuredOptionClaim:
        prompt = OPTION_CLAIM_PROMPT.format(
            question=question,
            scenario_setup=scenario_smt2 or "NONE",
            answer_text=answer_text,
            foundation_smt2=document_model.foundation_smt2,
        )
        try:
            payload = self.prompt_client.generate_json(prompt)
        except Exception:
            return StructuredOptionClaim(kind="unknown", proposition=None)

        kind = payload.get("kind", "unknown")
        if kind not in ("claim", "underdetermined", "unknown"):
            return StructuredOptionClaim(kind="unknown", proposition=None)

        proposition = payload.get("proposition")
        if isinstance(proposition, str):
            proposition = self._extract_expression(proposition)
        else:
            proposition = None

        return StructuredOptionClaim(kind=kind, proposition=proposition)

    def _build_base_program(self, foundation_smt2: str, scenario_smt2: str) -> str:
        parts = [foundation_smt2.rstrip()]
        if scenario_smt2:
            parts.extend(["", "; --- Scenario ---", scenario_smt2.rstrip()])
        return "\n".join(parts)

    def _run_solver_check(self, base_program: str, expression: str) -> VerificationResult:
        program = "\n".join(
            [
                base_program.rstrip(),
                "",
                "; Query: staged_document_verification",
                "(push 1)",
                f"(assert {expression})",
                "(check-sat)",
                "(get-model)",
                "(pop 1)",
            ]
        )
        return self.backend.execute_from_string(program)

    def _classify_proposition_status(
        self,
        support_result: VerificationResult,
        contradiction_result: VerificationResult,
    ) -> VerificationStatus:
        if not support_result.success or not contradiction_result.success:
            return "error"
        if support_result.answer is True and contradiction_result.answer is False:
            return "supported"
        if support_result.answer is False and contradiction_result.answer is True:
            return "contradicted"
        if support_result.answer is True and contradiction_result.answer is True:
            return "unresolved"
        return "error"

    def _classify_option_from_claim_kind(
        self,
        proposition_status: VerificationStatus,
        claim_kind: OptionClaimKind,
    ) -> VerificationStatus:
        if proposition_status == "error" or claim_kind == "unknown":
            return "error"
        if claim_kind == "claim":
            return proposition_status
        if claim_kind == "underdetermined":
            return "supported" if proposition_status == "unresolved" else "contradicted"
        return "error"

    def _derive_question_status(
        self,
        options: list[OptionVerificationResult],
    ) -> VerificationStatus:
        valid_option = next((option for option in options if option.option_type == "valid"), None)
        if valid_option is not None:
            return valid_option.status
        ambiguous_option = next(
            (option for option in options if option.option_type == "ambiguous"),
            None,
        )
        if ambiguous_option is not None and ambiguous_option.status == "supported":
            return "unresolved"
        return "error"

    def _load_dataset_records(
        self,
        dataset_path_or_records: str | Path | list[dict[str, Any]],
        selector: set[QuestionKey] | None,
        max_docs: int | None,
        max_pairs: int | None,
        company: str | None,
        industry: str | None,
        doc_type: str | None,
    ) -> list[dict[str, Any]]:
        if isinstance(dataset_path_or_records, (str, Path)):
            raw_records = self._load_raw_records_from_path(Path(dataset_path_or_records))
        else:
            raw_records = list(dataset_path_or_records)

        prepared_records: list[dict[str, Any]] = []
        remaining_pairs = max_pairs

        for raw_record in raw_records:
            prepared = self._prepare_record(raw_record)
            metadata = prepared["metadata"]

            if company and metadata.get("company") != company:
                continue
            if industry and metadata.get("industry") != industry:
                continue
            if doc_type and metadata.get("doc_type") != doc_type:
                continue

            qa_items = []
            for qa_item in prepared["qa_items"]:
                question_key = self._question_key(metadata, qa_item["qa_pair"]["question"])
                if selector and question_key not in selector:
                    continue
                if remaining_pairs is not None and remaining_pairs <= 0:
                    break
                qa_items.append(qa_item)
                if remaining_pairs is not None:
                    remaining_pairs -= 1

            if not qa_items:
                continue

            prepared["qa_items"] = qa_items
            prepared_records.append(prepared)

            if max_docs is not None and len(prepared_records) >= max_docs:
                break
            if remaining_pairs is not None and remaining_pairs <= 0:
                break

        return prepared_records

    def _load_raw_records_from_path(self, path: Path) -> list[dict[str, Any]]:
        if path.is_dir():
            paths = sorted(path.glob("*.json"))
        else:
            paths = [path]

        raw_records = []
        for record_path in paths:
            data = json.loads(record_path.read_text(encoding="utf-8"))
            data["source_path"] = str(record_path)
            raw_records.append(data)
        return raw_records

    def _prepare_record(self, record: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(record.get("metadata", {}))
        chunks = record.get("chunks")
        if not isinstance(chunks, list):
            raise ValueError("Dataset record must contain a 'chunks' list.")

        qa_items = []
        normalized_chunks = []
        for chunk_entry in chunks:
            normalized = self._normalize_chunk(chunk_entry)
            normalized_chunks.append(normalized)
            for qa_pair in normalized.get("qa_pairs", []):
                qa_items.append(
                    {
                        "chunk_index": normalized["chunk_index"],
                        "chunk_text": normalized["text"],
                        "qa_pair": qa_pair,
                    }
                )

        document_text = record.get("document_text")
        if not isinstance(document_text, str) or not document_text.strip():
            document_text = "\n\n".join(chunk["text"] for chunk in normalized_chunks).strip()

        return {
            "metadata": metadata,
            "chunks": normalized_chunks,
            "document_text": document_text,
            "qa_items": qa_items,
            "source_path": record.get("source_path"),
        }

    def _normalize_chunk(self, chunk_entry: dict[str, Any]) -> dict[str, Any]:
        chunk = chunk_entry.get("chunk", chunk_entry)
        return {
            "chunk_index": chunk["chunk_index"],
            "sentence_start": chunk.get("sentence_start"),
            "sentence_end": chunk.get("sentence_end"),
            "num_sentences": chunk.get("num_sentences"),
            "text": chunk["text"],
            "qa_pairs": list(chunk_entry.get("qa_pairs", chunk.get("qa_pairs", []))),
        }

    def _flatten_qa_pairs(self, document_model: DocumentModel) -> list[dict[str, Any]]:
        qa_items = []
        for chunk in document_model.chunks:
            for qa_pair in chunk.qa_pairs:
                qa_items.append(
                    {
                        "chunk_index": chunk.chunk_index,
                        "chunk_text": chunk.text,
                        "qa_pair": qa_pair,
                    }
                )
        return qa_items

    def _load_question_selector(
        self,
        sample_filter: str | Path | set[QuestionKey] | None,
    ) -> set[QuestionKey] | None:
        if sample_filter is None:
            return None
        if isinstance(sample_filter, set):
            return sample_filter

        sample_path = Path(sample_filter)
        sample_rows = json.loads(sample_path.read_text(encoding="utf-8"))
        return {self._question_key(row, row["question"]) for row in sample_rows}

    def _question_key(self, metadata: dict[str, Any], question: str) -> QuestionKey:
        return (
            str(metadata.get("company", "")),
            str(metadata.get("industry", "")),
            str(metadata.get("doc_type", "")),
            question,
        )

    def _compose_stage_fragment(self, stage_outputs: dict[str, str]) -> str:
        parts = []
        for stage_name in FOUNDATION_STAGES:
            output = stage_outputs.get(stage_name, "").strip()
            if not output:
                continue
            parts.append(f"; --- {stage_name.replace('_', ' ').title()} ---")
            parts.append(output)
            parts.append("")
        return "\n".join(parts).rstrip()

    def _enrich_document_context(
        self,
        context: ConversionContext,
        chunks: list[dict[str, Any]],
    ) -> None:
        chunk_texts = [str(chunk.get("text", "")) for chunk in chunks]
        self._materialize_state_agreement_groups(context, chunk_texts)

    def _materialize_state_agreement_groups(
        self,
        context: ConversionContext,
        chunk_texts: list[str],
    ) -> None:
        agreement_function = context.functions.get("user_agreement_for_state")
        if agreement_function is None:
            return

        state_sort_name, function_template = self._resolve_state_agreement_mapping(
            context,
            agreement_function.domain,
        )
        if state_sort_name is None or function_template is None:
            return

        agreement_sort_name = agreement_function.range_sort
        state_sort = context.sorts.get(state_sort_name)
        if state_sort is None or state_sort.kind != SMTSortKind.ENUM:
            return

        enum_values = set(state_sort.params.get("values", []))
        if not enum_values:
            return

        groups = self._extract_resident_state_groups(
            chunk_texts=chunk_texts,
            enum_values=enum_values,
            symbol_aliases=context.symbol_aliases,
        )
        if len(groups) < 2:
            return

        group_constant_names = []
        for index, states in enumerate(groups, start=1):
            constant_name = f"agreement_group_{index}"
            group_constant_names.append(constant_name)
            if constant_name not in context.constants:
                context.constants[constant_name] = SMTConstant(
                    name=constant_name,
                    smt_name=constant_name,
                    sort=agreement_sort_name,
                    smt_code=f"(declare-const {constant_name} {agreement_sort_name})",
                    emitted=True,
                )

            for state in states:
                self._ensure_kb_assertion(
                    context,
                    f"(assert (= {function_template.format(state=state)} {constant_name}))",
                )

        if len(group_constant_names) > 1:
            distinct_names = " ".join(group_constant_names)
            self._ensure_kb_assertion(
                context,
                f"(assert (distinct {distinct_names}))",
            )

    def _extract_resident_state_groups(
        self,
        chunk_texts: list[str],
        enum_values: set[str],
        symbol_aliases: dict[str, str],
    ) -> list[list[str]]:
        groups: list[list[str]] = []
        seen_groups: set[tuple[str, ...]] = set()

        for text in chunk_texts:
            for match in re.finditer(
                r"Residents\s+of\s+(.+?)\s+are\s+subject\s+to\b",
                text,
                flags=re.IGNORECASE | re.DOTALL,
            ):
                raw_states = re.findall(r"\b[A-Z]{2}\b", match.group(1))
                states: list[str] = []
                for raw_state in raw_states:
                    canonical = symbol_aliases.get(raw_state, raw_state.lower())
                    if canonical not in enum_values or canonical in states:
                        continue
                    states.append(canonical)

                if not states:
                    continue

                group_key = tuple(states)
                if group_key in seen_groups:
                    continue
                seen_groups.add(group_key)
                groups.append(states)

        return groups

    def _resolve_state_agreement_mapping(
        self,
        context: ConversionContext,
        domain: list[str],
    ) -> tuple[str | None, str | None]:
        if len(domain) == 1:
            return domain[0], "(user_agreement_for_state {state})"

        if len(domain) == 2:
            for index, sort_name in enumerate(domain):
                sort = context.sorts.get(sort_name)
                if sort is None or sort.kind != SMTSortKind.ENUM:
                    continue

                other_index = 1 - index
                platform_constant = self._find_constant_for_sort(context, domain[other_index])
                if platform_constant is None:
                    return None, None

                if index == 0:
                    return sort_name, f"(user_agreement_for_state {{state}} {platform_constant})"
                return sort_name, f"(user_agreement_for_state {platform_constant} {{state}})"

        return None, None

    def _find_constant_for_sort(
        self,
        context: ConversionContext,
        sort_name: str,
    ) -> str | None:
        preferred_name = "gemini"
        if (
            preferred_name in context.constants
            and context.constants[preferred_name].sort == sort_name
        ):
            return preferred_name

        for constant_name, constant in context.constants.items():
            if constant.sort == sort_name:
                return constant_name

        return None

    def _ensure_kb_assertion(
        self,
        context: ConversionContext,
        smt_code: str,
    ) -> None:
        if any(assertion.smt_code == smt_code for assertion in context.kb_assertions.values()):
            return

        assertion_id = f"kb_{len(context.kb_assertions)}"
        context.kb_assertions[assertion_id] = SMTAssertion(
            id=assertion_id,
            dsl_expr="",
            smt_expr=smt_code,
            smt_code=smt_code,
            emitted=True,
        )

    def _calculate_document_metrics(
        self,
        question_results: list[QuestionVerificationResult],
    ) -> DocumentVerificationMetrics:
        options = [option for question in question_results for option in question.options]
        correct = sum(1 for option in options if option.is_correct)
        failed = sum(1 for option in options if option.status == "error")
        incorrect = len(options) - correct - failed
        answered = correct + incorrect
        supported = sum(1 for option in options if option.status == "supported")
        unsound_supported = sum(
            1
            for option in options
            if option.status == "supported" and option.expected_status == "contradicted"
        )

        return DocumentVerificationMetrics(
            total_questions=len(question_results),
            total_options=len(options),
            correct_options=correct,
            incorrect_options=incorrect,
            failed_options=failed,
            supported_options=supported,
            unsound_supported_options=unsound_supported,
            contradicted_options=sum(1 for option in options if option.status == "contradicted"),
            unresolved_options=sum(1 for option in options if option.status == "unresolved"),
            accuracy=(correct / answered) if answered else 0.0,
            soundness=1.0 - (unsound_supported / supported) if supported else 1.0,
        )

    def _calculate_dataset_metrics(
        self,
        document_results: list[DocumentVerificationResult],
        documents_failed: int,
    ) -> DatasetEvaluationMetrics:
        total_questions = sum(
            result.metrics.total_questions for result in document_results if result.metrics
        )
        total_options = sum(
            result.metrics.total_options for result in document_results if result.metrics
        )
        correct = sum(
            result.metrics.correct_options for result in document_results if result.metrics
        )
        incorrect = sum(
            result.metrics.incorrect_options for result in document_results if result.metrics
        )
        failed = sum(result.metrics.failed_options for result in document_results if result.metrics)
        supported = sum(
            result.metrics.supported_options for result in document_results if result.metrics
        )
        unsound_supported = sum(
            result.metrics.unsound_supported_options
            for result in document_results
            if result.metrics
        )
        answered = correct + incorrect

        return DatasetEvaluationMetrics(
            documents_processed=len(document_results),
            documents_failed=documents_failed,
            total_questions=total_questions,
            total_options=total_options,
            correct_options=correct,
            incorrect_options=incorrect,
            failed_options=failed,
            supported_options=supported,
            unsound_supported_options=unsound_supported,
            contradicted_options=sum(
                result.metrics.contradicted_options for result in document_results if result.metrics
            ),
            unresolved_options=sum(
                result.metrics.unresolved_options for result in document_results if result.metrics
            ),
            accuracy=(correct / answered) if answered else 0.0,
            soundness=1.0 - (unsound_supported / supported) if supported else 1.0,
        )

    def _persist_document_artifacts(
        self,
        document_model: DocumentModel,
        result: DocumentVerificationResult,
    ) -> None:
        if not self.output_dir:
            return

        document_key = self._document_slug(document_model.metadata)
        models_dir = self.output_dir / "document_models"
        results_dir = self.output_dir / "document_results"
        programs_dir = self.output_dir / "document_programs"

        models_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)
        programs_dir.mkdir(parents=True, exist_ok=True)

        (models_dir / f"{document_key}.json").write_text(
            json.dumps(asdict(document_model), indent=2),
            encoding="utf-8",
        )
        (results_dir / f"{document_key}.json").write_text(
            json.dumps(asdict(result), indent=2),
            encoding="utf-8",
        )
        (programs_dir / f"{document_key}.smt2").write_text(
            document_model.foundation_smt2,
            encoding="utf-8",
        )
        logger.info(
            "Persisted artifacts for %s under %s",
            document_key,
            self.output_dir,
        )

    def _persist_document_error(
        self,
        metadata: dict[str, Any],
        source_path: str | None,
        exc: Exception,
    ) -> None:
        if not self.output_dir:
            return

        errors_dir = self.output_dir / "document_errors"
        errors_dir.mkdir(parents=True, exist_ok=True)

        error_payload = {
            "metadata": metadata,
            "source_path": source_path,
            "error": str(exc),
        }
        document_key = self._document_slug(metadata)
        (errors_dir / f"{document_key}.json").write_text(
            json.dumps(error_payload, indent=2),
            encoding="utf-8",
        )

    def _persist_dataset_metrics(self, result: DatasetEvaluationResult) -> None:
        if not self.output_dir:
            return
        (self.output_dir / "aggregate_metrics.json").write_text(
            json.dumps(asdict(result.metrics), indent=2),
            encoding="utf-8",
        )

    def _document_slug(self, metadata: dict[str, Any]) -> str:
        raw = "__".join(
            [
                str(metadata.get("industry", "unknown")),
                str(metadata.get("company", "unknown")),
                str(metadata.get("doc_type", "unknown")),
            ]
        )
        return re.sub(r"[^A-Za-z0-9._-]+", "-", raw)

    def _summarize_question(self, question: str, max_length: int = 120) -> str:
        normalized = " ".join(question.split())
        if len(normalized) <= max_length:
            return normalized
        return f"{normalized[: max_length - 3]}..."

    def _solver_result_to_status(self, result: VerificationResult) -> str:
        if not result.success:
            return "error"
        if result.answer is True:
            return "sat"
        if result.answer is False:
            return "unsat"
        return "unknown"

    def _question_error(
        self,
        support_result: VerificationResult,
        contradiction_result: VerificationResult,
    ) -> str | None:
        if support_result.success and contradiction_result.success:
            return None
        errors = []
        if support_result.error:
            errors.append(f"support_check: {support_result.error}")
        if contradiction_result.error:
            errors.append(f"contradiction_check: {contradiction_result.error}")
        return "; ".join(errors) if errors else None

    def _aggregate_option_errors(
        self,
        options: list[OptionVerificationResult],
    ) -> str | None:
        errors = [option.error for option in options if option.error]
        if not errors:
            return None
        unique_errors = list(dict.fromkeys(errors))
        return " | ".join(unique_errors)

    def _extract_scenario_setup(self, raw_output: str) -> str:
        cleaned = self._clean_output(raw_output)
        if not cleaned or cleaned.upper() == "NONE":
            return ""

        forbidden_patterns = (
            r"\(check-sat\)",
            r"\(get-model\)",
            r"\(push\s+\d+\)",
            r"\(pop\s+\d+\)",
        )
        for pattern in forbidden_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

        forms = self._extract_command_forms(cleaned, ("declare-const", "assert"))
        return "\n".join(forms)

    def _sanitize_scenario_setup(
        self,
        scenario_setup: str,
        document_context: dict[str, Any],
    ) -> str:
        if not scenario_setup.strip():
            return ""

        reserved_symbols = set(document_context.get("functions", {}).keys())
        reserved_symbols.update(document_context.get("constants", {}).keys())
        reserved_symbols.update(document_context.get("sorts", {}).keys())
        for sort_entry in document_context.get("sorts", {}).values():
            params = sort_entry.get("params", {})
            reserved_symbols.update(params.get("values", []))

        renames: dict[str, str] = {}
        used_symbols = set(reserved_symbols)
        for match in re.finditer(r"\(declare-const\s+(\w+)\s+(\w+)\)", scenario_setup):
            original_name = match.group(1)
            base_name = original_name
            if not base_name.startswith("scenario_"):
                base_name = f"scenario_{base_name}"

            candidate = base_name
            suffix = 1
            while candidate in used_symbols:
                suffix += 1
                candidate = f"{base_name}_{suffix}"

            renames[original_name] = candidate
            used_symbols.add(candidate)

        rewritten = scenario_setup
        for original_name, rewritten_name in sorted(
            renames.items(),
            key=lambda item: -len(item[0]),
        ):
            rewritten = re.sub(rf"\b{re.escape(original_name)}\b", rewritten_name, rewritten)

        return rewritten

    def _extract_expression(self, raw_output: str) -> str | None:
        cleaned = self._clean_output(raw_output)
        if not cleaned or cleaned.upper() == "UNKNOWN":
            return None

        expression = self._first_s_expression(cleaned)
        if expression is None:
            return None

        if expression.startswith("(assert "):
            match = re.match(r"^\(assert\s+(.+)\)$", expression, flags=re.DOTALL)
            if match:
                expression = match.group(1).strip()

        return expression.strip()

    def _clean_output(self, text: str) -> str:
        text = re.sub(r"```(?:smt2|text|json)?\s*", "", text)
        text = re.sub(r"```", "", text)
        lines = [line for line in text.splitlines() if not line.strip().startswith(";")]
        return "\n".join(lines).strip()

    def _first_s_expression(self, text: str) -> str | None:
        start = text.find("(")
        if start == -1:
            return None

        depth = 0
        for index, char in enumerate(text[start:], start):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1].strip()
        return None

    def _extract_command_forms(
        self,
        text: str,
        command_names: tuple[str, ...],
    ) -> list[str]:
        forms = []
        search_start = 0
        command_pattern = "|".join(re.escape(name) for name in command_names)

        while True:
            match = re.search(rf"\((?:{command_pattern})\b", text[search_start:])
            if not match:
                break

            start = search_start + match.start()
            depth = 0
            end = start
            for index, char in enumerate(text[start:], start):
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break

            if end > start:
                forms.append(text[start:end].strip())
                search_start = end
            else:
                break

        return forms

    def _strip_front_matter(self, text: str) -> str:
        if not text.startswith("---"):
            return text
        match = re.match(r"^---\n.*?\n---\n?", text, flags=re.DOTALL)
        if not match:
            return text
        return text[match.end() :]


def build_document_model(
    proof_of_thought: ProofOfThought,
    document_text: str,
    chunks: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    source_path: str | None = None,
) -> DocumentModel:
    """Build a staged document model using a ProofOfThought instance."""
    pipeline = DocumentVerificationPipeline(proof_of_thought)
    return pipeline.build_document_model(
        document_text=document_text,
        chunks=chunks,
        metadata=metadata,
        source_path=source_path,
    )


def verify_qa_pairs(
    proof_of_thought: ProofOfThought,
    document_model: DocumentModel,
    qa_pairs: list[dict[str, Any]] | None = None,
) -> DocumentVerificationResult:
    """Verify QA pairs using a staged document model."""
    pipeline = DocumentVerificationPipeline(proof_of_thought)
    return pipeline.verify_qa_pairs(document_model=document_model, qa_pairs=qa_pairs)


def evaluate_dataset(
    proof_of_thought: ProofOfThought,
    dataset_path_or_records: str | Path | list[dict[str, Any]],
    sample_filter: str | Path | set[QuestionKey] | None = None,
    max_docs: int | None = None,
    max_pairs: int | None = None,
    company: str | None = None,
    industry: str | None = None,
    doc_type: str | None = None,
    output_dir: str | Path | None = None,
) -> DatasetEvaluationResult:
    """Evaluate an NL-SMT-Bench-style dataset."""
    pipeline = DocumentVerificationPipeline(proof_of_thought, output_dir=output_dir)
    return pipeline.evaluate_dataset(
        dataset_path_or_records=dataset_path_or_records,
        sample_filter=sample_filter,
        max_docs=max_docs,
        max_pairs=max_pairs,
        company=company,
        industry=industry,
        doc_type=doc_type,
    )


def load_question_selector(sample_filter_path: str | Path) -> set[QuestionKey]:
    """Load a qa_sample-style selector file into question keys."""
    sample_rows = json.loads(Path(sample_filter_path).read_text(encoding="utf-8"))
    return {
        (
            str(row.get("company", "")),
            str(row.get("industry", "")),
            str(row.get("doc_type", "")),
            row["question"],
        )
        for row in sample_rows
    }
