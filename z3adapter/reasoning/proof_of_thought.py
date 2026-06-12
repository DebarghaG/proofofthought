"""ProofOfThought: Main API for Z3-based reasoning."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import traceback
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from z3adapter.agentic.executor import verdict_counts
from z3adapter.reasoning.program_generator import Z3ProgramGenerator

if TYPE_CHECKING:
    from z3adapter.agentic.agent import AgenticConfig, AgenticSolver
    from z3adapter.backends.abstract import Backend
    from z3adapter.postprocessors.abstract import Postprocessor

logger = logging.getLogger(__name__)

BackendType = Literal["agentic", "json", "smt2"]

# NOTE: "sat"/"unsat" are deliberately NOT in these sets. Under the agentic
# proof-by-contradiction discipline a clean `unsat` *proves* the candidate
# answer (whatever its polarity), so a raw verdict appearing as the finish
# answer is ambiguous and must not be coerced to a boolean.
_TRUE_ANSWERS = {"yes", "true", "valid", "verified"}
_FALSE_ANSWERS = {"no", "false", "invalid", "violated"}


def answer_text_to_bool(answer: str | None) -> bool | None:
    """Map a free-form answer to a boolean when it is unambiguously boolean-like.

    Returns None for anything outside the small yes/no vocabulary - including
    multiple-choice letters, numbers, and raw Z3 verdicts - rather than
    guessing. Callers needing richer matching (aliases, letters, locales)
    should compare ``answer_text`` themselves.
    """
    if answer is None:
        return None
    a = answer.strip().lower().rstrip(".")
    if a in _TRUE_ANSWERS:
        return True
    if a in _FALSE_ANSWERS:
        return False
    return None


@dataclass
class QueryResult:
    """Result of a reasoning query.

    Field contract (uniform across backends):

    - ``answer_text`` is the **canonical answer** - always populated when an
      answer was produced, for every backend ("True"/"False" for the
      single-shot backends, the raw finish() value for agentic). Prefer it
      for anything that isn't strictly boolean.
    - ``answer`` is the boolean view of ``answer_text``; None when the answer
      is not boolean-like (e.g. a multiple-choice letter) **or** when no
      answer was produced - check ``success`` to tell the two apart.
    - ``success`` means "an answer was produced". It does NOT imply formal
      verification on the agentic backend; that is what ``verified`` and
      ``proof_status`` are for.
    - ``verified`` (agentic only): the finish() call was backed by a decisive
      Z3 verdict. ``proof_status`` says how - "proof_by_contradiction",
      "sat_witness", or "unverified" (see ``z3adapter.agentic.ProofStatus``);
      None on the single-shot backends and when no answer was produced.
    """

    question: str
    answer: bool | None
    json_program: dict[str, Any] | None
    sat_count: int
    unsat_count: int
    output: str
    success: bool
    num_attempts: int
    error: str | None = None
    answer_text: str | None = None
    smt_history: list[dict[str, Any]] | None = None
    iterations: int = 0
    verified: bool = False
    proof_status: str | None = None


class ProofOfThought:
    """High-level API for Z3-based reasoning.

    The default backend is **agentic**: the model iteratively interacts with
    an SMT-LIB scratchpad through ``z3_solve`` tool calls, inspects Z3's
    verdict, repairs its encoding, and terminates with an explicit ``finish``
    call. Each answer carries a ``proof_status`` describing how the
    trajectory backs it (canonically a proof by contradiction - a clean
    UNSAT of the negated candidate). This is the paradigm the library is
    moving towards going forward. The classic single-shot ``smt2`` and
    ``json`` backends remain fully supported.

    Example:
        >>> from openai import OpenAI
        >>> client = OpenAI(api_key="...")
        >>> pot = ProofOfThought(llm_client=client)  # agentic by default
        >>> result = pot.query("Would Nancy Pelosi publicly denounce abortion?")
        >>> print(result.answer)        # False
        >>> print(result.proof_status)  # "proof_by_contradiction"
    """

    def __init__(
        self,
        llm_client: Any,
        model: str = "gpt-5",
        backend: BackendType = "agentic",
        max_attempts: int = 3,
        max_iterations: int = 10,
        verify_timeout: int = 10000,
        optimize_timeout: int = 100000,
        cache_dir: str | None = None,
        z3_path: str = "z3",
        postprocessors: Sequence[str | Postprocessor] | None = None,
        postprocessor_configs: dict[str, dict] | None = None,
        agentic_config: AgenticConfig | None = None,
    ) -> None:
        """Initialize ProofOfThought.

        Args:
            llm_client: LLM client (OpenAI, AzureOpenAI, Anthropic, etc.)
            model: LLM model/deployment name (default: "gpt-5")
            backend: Execution backend ("agentic", "smt2" or "json";
                default: "agentic")
            max_attempts: Maximum retry attempts for program generation
                (json/smt2 backends only)
            max_iterations: Maximum tool-loop iterations (agentic backend only)
            verify_timeout: Z3 verification timeout in milliseconds. Governs
                all backends, including the agentic loop's in-process Z3.
            optimize_timeout: Z3 optimization timeout in milliseconds (json)
            cache_dir: Directory to cache generated programs (None = temp dir)
            z3_path: Path to Z3 executable (for SMT2 backend)
            postprocessors: List of postprocessor names or instances to apply.
                Only supported with the json/smt2 backends; configuring them
                with the agentic backend raises ValueError at construction.
            postprocessor_configs: Configuration for postprocessors (if names provided)
            agentic_config: Optional ``z3adapter.agentic.AgenticConfig`` for
                full control over the agentic loop. When provided it is
                authoritative: the ``model``, ``max_iterations`` and
                ``verify_timeout`` arguments are not applied to it (a warning
                is logged if ``model`` conflicts).

        Example with postprocessors:
            >>> pot = ProofOfThought(
            ...     llm_client=client,
            ...     backend="smt2",
            ...     postprocessors=["self_refine", "self_consistency"],
            ...     postprocessor_configs={"self_refine": {"num_iterations": 3}}
            ... )
        """
        self.backend_type = backend
        self.llm_client = llm_client

        if backend == "agentic" and postprocessors:
            # Fail at the declaration site, not with a buried runtime warning:
            # postprocessors drive the single-shot generator/backend pair and
            # have no defined meaning inside the tool loop (yet).
            raise ValueError(
                "Postprocessors are only supported with the 'smt2' and 'json' "
                "backends. Pass backend='smt2' (or 'json') to use them, or drop "
                "the postprocessors argument for the agentic backend."
            )

        # The single-shot generator is only meaningful for json/smt2; the
        # agentic path generates programs inside the tool loop. Keeping it
        # None there makes accidental misuse fail loudly instead of silently
        # producing single-shot prompts under the wrong paradigm.
        self.generator: Z3ProgramGenerator | None = None
        if backend != "agentic":
            generator_backend: Literal["json", "smt2"] = "json" if backend == "json" else "smt2"
            self.generator = Z3ProgramGenerator(
                llm_client=llm_client, model=model, backend=generator_backend
            )

        # Initialize appropriate backend (import here to avoid circular imports)
        self.agentic_solver: AgenticSolver | None = None
        if backend == "agentic":
            from z3adapter.agentic.agent import AgenticConfig, AgenticSolver
            from z3adapter.backends.agentic_backend import AgenticBackend

            if agentic_config is None:
                agentic_config = AgenticConfig(
                    model=model,
                    max_iterations=max_iterations,
                    z3_timeout_ms=verify_timeout,
                )
            elif model != "gpt-5" and agentic_config.model != model:
                logger.warning(
                    "agentic_config.model=%r overrides the model=%r argument; "
                    "set the model on AgenticConfig when passing one.",
                    agentic_config.model,
                    model,
                )
            self.agentic_solver = AgenticSolver(llm_client=llm_client, config=agentic_config)
            backend_instance: Backend = AgenticBackend(verify_timeout=agentic_config.z3_timeout_ms)
        elif backend == "json":
            from z3adapter.backends.json_backend import JSONBackend

            backend_instance = JSONBackend(
                verify_timeout=verify_timeout, optimize_timeout=optimize_timeout
            )
        else:  # smt2
            from z3adapter.backends.smt2_backend import SMT2Backend

            backend_instance = SMT2Backend(verify_timeout=verify_timeout, z3_path=z3_path)

        self.backend = backend_instance

        self.max_attempts = max_attempts
        self.cache_dir = cache_dir or tempfile.gettempdir()

        # Create cache directory if needed
        os.makedirs(self.cache_dir, exist_ok=True)

        # Initialize postprocessors
        self.postprocessors: list[Postprocessor] = []
        if postprocessors:
            self.postprocessors = self._initialize_postprocessors(
                postprocessors, postprocessor_configs or {}
            )
            logger.info(f"Initialized {len(self.postprocessors)} postprocessors")

    def _initialize_postprocessors(
        self,
        postprocessors: Sequence[str | Postprocessor],
        configs: dict[str, dict],
    ) -> list[Postprocessor]:
        """Initialize postprocessor instances from names or objects.

        Args:
            postprocessors: List of postprocessor names or instances
            configs: Configuration dict for postprocessors

        Returns:
            List of postprocessor instances
        """
        from z3adapter.postprocessors.abstract import Postprocessor
        from z3adapter.postprocessors.registry import PostprocessorRegistry

        initialized = []
        for item in postprocessors:
            if isinstance(item, str):
                # Create from registry
                config = configs.get(item, {})
                postprocessor = PostprocessorRegistry.get(item, **config)
                initialized.append(postprocessor)
            elif isinstance(item, Postprocessor):
                # Already an instance
                initialized.append(item)
            else:
                logger.warning(f"Invalid postprocessor: {item}, skipping")

        return initialized

    def query(
        self,
        question: str,
        temperature: float | None = None,
        max_tokens: int = 16384,
        save_program: bool = False,
        program_path: str | None = None,
        enable_postprocessing: bool = True,
    ) -> QueryResult:
        """Answer a reasoning question using Z3 theorem proving.

        Args:
            question: Natural language question to answer
            temperature: Sampling temperature, honored on every backend.
                None (default) sends nothing and uses the provider default -
                required for models like GPT-5 that reject non-default
                temperatures.
            max_tokens: Maximum tokens per LLM response (default 16384)
            save_program: Whether to save the generated program (the final
                trajectory program for the agentic backend)
            program_path: Path to save program (None = auto-generate)
            enable_postprocessing: Whether to apply postprocessors (if configured)

        Returns:
            QueryResult with answer and execution details
        """
        logger.info(f"Processing question: {question}")

        if self.backend_type == "agentic":
            return self._query_agentic(
                question=question,
                temperature=temperature,
                max_tokens=max_tokens,
                save_program=save_program,
                program_path=program_path,
            )

        assert self.generator is not None
        previous_response: str | None = None
        error_trace: str | None = None

        for attempt in range(1, self.max_attempts + 1):
            logger.info(f"Attempt {attempt}/{self.max_attempts}")

            try:
                # Generate or regenerate program
                if attempt == 1:
                    gen_result = self.generator.generate(
                        question=question,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                else:
                    gen_result = self.generator.generate_with_feedback(
                        question=question,
                        error_trace=error_trace or "",
                        previous_response=previous_response or "",
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )

                if not gen_result.success or gen_result.program is None:
                    error_trace = (
                        gen_result.error or f"Failed to generate {self.backend_type} program"
                    )
                    previous_response = gen_result.raw_response
                    logger.warning(f"Generation failed: {error_trace}")
                    continue

                # Save program to temporary file
                file_extension = self.backend.get_file_extension()
                if program_path is None:
                    temp_file = tempfile.NamedTemporaryFile(
                        mode="w",
                        suffix=file_extension,
                        dir=self.cache_dir,
                        delete=not save_program,
                    )
                    program_file_path = temp_file.name
                else:
                    program_file_path = program_path

                # Write program to file (format depends on backend)
                with open(program_file_path, "w") as f:
                    if self.backend_type == "json":
                        json.dump(gen_result.program, f, indent=2)
                    else:  # smt2
                        f.write(gen_result.program)  # type: ignore

                logger.info(f"Generated program saved to: {program_file_path}")

                # Execute via backend
                verify_result = self.backend.execute(program_file_path)

                if not verify_result.success:
                    error_trace = verify_result.error or "Z3 verification failed"
                    previous_response = gen_result.raw_response
                    logger.warning(f"Verification failed: {error_trace}")
                    continue

                # Check if we got a definitive answer
                if verify_result.answer is None:
                    error_trace = (
                        f"Ambiguous verification result: "
                        f"SAT={verify_result.sat_count}, UNSAT={verify_result.unsat_count}\n"
                        f"Output:\n{verify_result.output}"
                    )
                    previous_response = gen_result.raw_response
                    logger.warning(f"Ambiguous result: {error_trace}")
                    continue

                # Success!
                logger.info(
                    f"Successfully answered question on attempt {attempt}: {verify_result.answer}"
                )
                initial_result = QueryResult(
                    question=question,
                    answer=verify_result.answer,
                    json_program=gen_result.json_program,  # For backward compatibility
                    sat_count=verify_result.sat_count,
                    unsat_count=verify_result.unsat_count,
                    output=verify_result.output,
                    success=True,
                    num_attempts=attempt,
                    answer_text=str(verify_result.answer),
                )

                # Apply postprocessors if enabled
                if enable_postprocessing and self.postprocessors:
                    logger.info(
                        f"Applying {len(self.postprocessors)} postprocessors to improve result"
                    )
                    return self._apply_postprocessors(
                        question=question,
                        initial_result=initial_result,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )

                return initial_result

            except Exception as e:
                error_trace = f"Error: {str(e)}\n{traceback.format_exc()}"
                logger.error(f"Exception on attempt {attempt}: {error_trace}")
                if "gen_result" in locals():
                    previous_response = gen_result.raw_response

        # All attempts failed
        logger.error(f"Failed to answer question after {self.max_attempts} attempts")
        return QueryResult(
            question=question,
            answer=None,
            json_program=None,
            sat_count=0,
            unsat_count=0,
            output="",
            success=False,
            num_attempts=self.max_attempts,
            error=f"Failed after {self.max_attempts} attempts. Last error: {error_trace}",
        )

    def _query_agentic(
        self,
        question: str,
        temperature: float | None,
        max_tokens: int,
        save_program: bool,
        program_path: str | None,
    ) -> QueryResult:
        """Answer a question via the agentic SMT-LIB scratchpad loop."""
        assert self.agentic_solver is not None

        result = self.agentic_solver.solve(question, temperature=temperature, max_tokens=max_tokens)

        # Persist the final (or last) SMT program of the trajectory so it can
        # be inspected / re-checked via AgenticBackend.reverify(). The default
        # filename is uniquified: a fixed name would be silently overwritten
        # by the next query (and races under caller-side threading).
        if (save_program or program_path) and result.smt_history:
            path = program_path or os.path.join(
                self.cache_dir,
                f"agentic_program_{uuid.uuid4().hex[:8]}{self.backend.get_file_extension()}",
            )
            try:
                with open(path, "w") as f:
                    f.write(result.smt_history[-1]["smt_code"])
                logger.info(f"Agentic program saved to: {path}")
            except OSError as e:
                logger.warning(f"Failed to save agentic program: {e}")

        last_z3 = result.smt_history[-1]["z3_output"] if result.smt_history else {}
        sat_count, unsat_count = verdict_counts(last_z3.get("sat_result"))
        # success = "an answer was produced". Verification strength is
        # reported separately via verified/proof_status - an UNVERIFIED
        # answer is still an answer, but never masquerades as a proof.
        has_answer = result.answer is not None and str(result.answer).strip() != ""
        return QueryResult(
            question=question,
            answer=answer_text_to_bool(result.answer),
            json_program=None,
            sat_count=sat_count,
            unsat_count=unsat_count,
            output=last_z3.get("output") or "",
            success=has_answer,
            num_attempts=result.iterations,
            error=result.error if not has_answer else None,
            answer_text=result.answer,
            smt_history=result.smt_history,
            iterations=result.iterations,
            verified=result.verified,
            proof_status=result.proof_status.value if result.proof_status else None,
        )

    def _apply_postprocessors(
        self,
        question: str,
        initial_result: QueryResult,
        temperature: float | None,
        max_tokens: int,
    ) -> QueryResult:
        """Apply all configured postprocessors to improve the result.

        Args:
            question: Original question
            initial_result: Initial QueryResult
            temperature: LLM temperature (None = provider default)
            max_tokens: Max tokens

        Returns:
            Enhanced QueryResult after applying all postprocessors
        """
        assert self.generator is not None  # postprocessors imply json/smt2
        current_result = initial_result

        for postprocessor in self.postprocessors:
            logger.info(f"Applying postprocessor: {postprocessor.name}")

            try:
                enhanced_result = postprocessor.process(
                    question=question,
                    initial_result=current_result,
                    generator=self.generator,
                    backend=self.backend,
                    llm_client=self.llm_client,
                    cache_dir=self.cache_dir,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                if enhanced_result.success:
                    logger.info(
                        f"Postprocessor {postprocessor.name} completed. "
                        f"Answer: {enhanced_result.answer}"
                    )
                    current_result = enhanced_result
                else:
                    logger.warning(
                        f"Postprocessor {postprocessor.name} failed, keeping previous result"
                    )

            except Exception as e:
                logger.error(f"Error in postprocessor {postprocessor.name}: {e}")
                # Continue with current result if postprocessor fails

        return current_result
