"""Self-Consistency postprocessor for improving answer reliability.

Based on the Self-Consistency technique from:
"Self-Consistency Improves Chain of Thought Reasoning in Language Models" (Wang et al., 2022)
"""

import json
import logging
import os
import tempfile
from collections import Counter
from typing import TYPE_CHECKING, Any

from z3adapter.postprocessors.abstract import Postprocessor

if TYPE_CHECKING:
    from z3adapter.backends.abstract import Backend
    from z3adapter.reasoning.program_generator import Z3ProgramGenerator
    from z3adapter.reasoning.proof_of_thought import QueryResult

logger = logging.getLogger(__name__)


class SelfConsistency(Postprocessor):
    """Self-Consistency postprocessor using majority voting.

    The Self-Consistency technique works by:
    1. Generating multiple independent reasoning paths
    2. Collecting answers from all paths
    3. Selecting the most consistent answer via majority voting

    This increases reliability by reducing the impact of random errors
    or spurious reasoning in any single attempt.
    """

    def __init__(self, num_samples: int = 5, name: str | None = None):
        """Initialize Self-Consistency postprocessor.

        Args:
            num_samples: Number of independent samples to generate
            name: Optional custom name for this postprocessor
        """
        super().__init__(name)
        self.num_samples = num_samples

    def process(
        self,
        question: str,
        initial_result: "QueryResult",
        generator: "Z3ProgramGenerator",
        backend: "Backend",
        llm_client: Any,
        **kwargs: Any,
    ) -> "QueryResult":
        """Apply Self-Consistency to improve answer reliability.

        Args:
            question: Original question
            initial_result: Initial QueryResult
            generator: Program generator
            backend: Execution backend
            llm_client: LLM client
            **kwargs: Additional arguments (cache_dir, temperature, max_tokens)

        Returns:
            QueryResult with most consistent answer
        """
        logger.info(
            f"[{self.name}] Starting self-consistency with {self.num_samples} samples "
            f"(including initial result)"
        )

        cache_dir = kwargs.get("cache_dir", tempfile.gettempdir())
        temperature = kwargs.get("temperature", 0.7)  # Higher temp for diversity
        max_tokens = kwargs.get("max_tokens", 16384)

        # Collect all results (including initial)
        all_results = [initial_result]
        answer_counts: Counter[bool | None] = Counter()

        # Count initial result
        if initial_result.success and initial_result.answer is not None:
            answer_counts[initial_result.answer] += 1

        # Generate additional samples
        num_additional = self.num_samples - 1
        for i in range(num_additional):
            logger.info(f"[{self.name}] Generating sample {i+2}/{self.num_samples}")

            sample_result = self._generate_sample(
                question=question,
                generator=generator,
                backend=backend,
                cache_dir=cache_dir,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            all_results.append(sample_result)

            if sample_result.success and sample_result.answer is not None:
                answer_counts[sample_result.answer] += 1
                logger.info(f"[{self.name}] Sample {i+2} answer: {sample_result.answer}")
            else:
                logger.warning(f"[{self.name}] Sample {i+2} failed")

        # Perform majority voting
        if not answer_counts:
            logger.warning(f"[{self.name}] No successful samples, returning initial result")
            return initial_result

        # Find most common answer
        majority_answer, count = answer_counts.most_common(1)[0]
        total_successful = sum(answer_counts.values())

        logger.info(
            f"[{self.name}] Majority vote: {majority_answer} "
            f"({count}/{total_successful} samples, "
            f"{count/total_successful:.1%} agreement)"
        )

        # Find the best result with the majority answer
        best_result = initial_result
        for result in all_results:
            if result.success and result.answer == majority_answer:
                # Prefer results with fewer attempts or clearer SAT/UNSAT counts
                if best_result.answer != majority_answer or self._is_better_result(
                    result, best_result
                ):
                    best_result = result

        # Add metadata about consistency
        logger.info(
            f"[{self.name}] Self-consistency complete. "
            f"Answer distribution: {dict(answer_counts)}"
        )

        return best_result

    def _generate_sample(
        self,
        question: str,
        generator: "Z3ProgramGenerator",
        backend: "Backend",
        cache_dir: str,
        temperature: float,
        max_tokens: int,
    ) -> "QueryResult":
        """Generate a single independent sample.

        Args:
            question: Original question
            generator: Program generator
            backend: Execution backend
            cache_dir: Cache directory
            temperature: LLM temperature (higher for diversity)
            max_tokens: Max tokens

        Returns:
            QueryResult from this sample
        """
        from z3adapter.reasoning.proof_of_thought import QueryResult

        try:
            # Generate new program with higher temperature for diversity
            gen_result = generator.generate(
                question=question,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            if not gen_result.success or gen_result.program is None:
                return QueryResult(
                    question=question,
                    answer=None,
                    json_program=None,
                    sat_count=0,
                    unsat_count=0,
                    output="",
                    success=False,
                    num_attempts=0,
                    error="Failed to generate program",
                )

            # Save and execute program
            file_extension = backend.get_file_extension()
            temp_file = tempfile.NamedTemporaryFile(
                mode="w",
                suffix=file_extension,
                dir=cache_dir,
                delete=False,
            )
            program_path = temp_file.name

            with open(program_path, "w") as f:
                if generator.backend == "json":
                    json.dump(gen_result.program, f, indent=2)
                else:
                    f.write(gen_result.program)  # type: ignore

            # Execute program
            verify_result = backend.execute(program_path)

            # Clean up temp file
            try:
                os.unlink(program_path)
            except Exception:
                pass

            return QueryResult(
                question=question,
                answer=verify_result.answer,
                json_program=gen_result.json_program,
                sat_count=verify_result.sat_count,
                unsat_count=verify_result.unsat_count,
                output=verify_result.output,
                success=verify_result.success and verify_result.answer is not None,
                num_attempts=1,
            )

        except Exception as e:
            logger.error(f"[{self.name}] Error generating sample: {e}")
            return QueryResult(
                question=question,
                answer=None,
                json_program=None,
                sat_count=0,
                unsat_count=0,
                output="",
                success=False,
                num_attempts=0,
                error=str(e),
            )

    def _is_better_result(self, result1: "QueryResult", result2: "QueryResult") -> bool:
        """Compare two results to determine which is better.

        Args:
            result1: First result
            result2: Second result

        Returns:
            True if result1 is better than result2
        """
        # Prefer results with fewer attempts (cleaner generation)
        if result1.num_attempts < result2.num_attempts:
            return True
        if result1.num_attempts > result2.num_attempts:
            return False

        # Prefer results with clearer SAT/UNSAT distinction
        result1_clarity = abs(result1.sat_count - result1.unsat_count)
        result2_clarity = abs(result2.sat_count - result2.unsat_count)

        return result1_clarity > result2_clarity
