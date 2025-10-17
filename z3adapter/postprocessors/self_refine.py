"""Self-Refine postprocessor for iterative refinement of reasoning.

Based on the Self-Refine technique from:
"Self-Refine: Iterative Refinement with Self-Feedback" (Madaan et al., 2023)
"""

import json
import logging
import os
import tempfile
from typing import TYPE_CHECKING, Any

from z3adapter.postprocessors.abstract import Postprocessor

if TYPE_CHECKING:
    from z3adapter.backends.abstract import Backend
    from z3adapter.reasoning.program_generator import Z3ProgramGenerator
    from z3adapter.reasoning.proof_of_thought import QueryResult

logger = logging.getLogger(__name__)


class SelfRefine(Postprocessor):
    """Self-Refine postprocessor for iterative improvement through self-feedback.

    The Self-Refine technique works by:
    1. Generating an initial solution
    2. Asking the LLM to provide feedback on its own solution
    3. Using that feedback to refine the solution
    4. Repeating until convergence or max iterations

    This postprocessor applies the technique to Z3 programs, asking the LLM to
    critique and improve its reasoning and logical encoding.
    """

    def __init__(self, num_iterations: int = 2, name: str | None = None):
        """Initialize Self-Refine postprocessor.

        Args:
            num_iterations: Maximum number of refinement iterations
            name: Optional custom name for this postprocessor
        """
        super().__init__(name)
        self.num_iterations = num_iterations

    def process(
        self,
        question: str,
        initial_result: "QueryResult",
        generator: "Z3ProgramGenerator",
        backend: "Backend",
        llm_client: Any,
        **kwargs: Any,
    ) -> "QueryResult":
        """Apply Self-Refine to improve the initial result.

        Args:
            question: Original question
            initial_result: Initial QueryResult
            generator: Program generator
            backend: Execution backend
            llm_client: LLM client
            **kwargs: Additional arguments (cache_dir, temperature, max_tokens)

        Returns:
            Refined QueryResult
        """
        logger.info(f"[{self.name}] Starting self-refinement with {self.num_iterations} iterations")

        # If initial result failed, return as-is
        if not initial_result.success:
            logger.warning(f"[{self.name}] Initial result failed, skipping refinement")
            return initial_result

        cache_dir = kwargs.get("cache_dir", tempfile.gettempdir())
        temperature = kwargs.get("temperature", 0.1)
        max_tokens = kwargs.get("max_tokens", 16384)

        current_result = initial_result
        best_result = initial_result

        for iteration in range(1, self.num_iterations + 1):
            logger.info(f"[{self.name}] Refinement iteration {iteration}/{self.num_iterations}")

            # Generate self-feedback
            feedback = self._generate_feedback(
                question=question,
                current_result=current_result,
                llm_client=llm_client,
                generator=generator,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            if not feedback or "no improvement needed" in feedback.lower():
                logger.info(f"[{self.name}] No further improvements suggested, stopping")
                break

            # Generate refined program with feedback
            refined_result = self._generate_refined_program(
                question=question,
                feedback=feedback,
                previous_result=current_result,
                generator=generator,
                backend=backend,
                cache_dir=cache_dir,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            if refined_result.success:
                current_result = refined_result
                # Keep track of best result (prefer successful results)
                if refined_result.answer == initial_result.answer:
                    # Confirmation of original answer increases confidence
                    best_result = refined_result
                    logger.info(f"[{self.name}] Refinement confirmed original answer")
                else:
                    logger.info(
                        f"[{self.name}] Refinement produced different answer: "
                        f"{refined_result.answer} vs {best_result.answer}"
                    )
                    # Keep the most refined successful result
                    best_result = refined_result
            else:
                logger.warning(f"[{self.name}] Refinement iteration {iteration} failed")

        logger.info(
            f"[{self.name}] Self-refinement complete. "
            f"Final answer: {best_result.answer}, "
            f"Initial answer: {initial_result.answer}"
        )

        return best_result

    def _generate_feedback(
        self,
        question: str,
        current_result: "QueryResult",
        llm_client: Any,
        generator: "Z3ProgramGenerator",
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Generate self-feedback on the current solution.

        Args:
            question: Original question
            current_result: Current QueryResult
            llm_client: LLM client
            generator: Program generator (for backend type)
            temperature: LLM temperature
            max_tokens: Max tokens for response

        Returns:
            Feedback string from LLM
        """
        # Format the current program for display
        if generator.backend == "json" and current_result.json_program:
            format_name = "JSON DSL"
        else:
            # For SMT2, we'd need to read the program file, but we don't have the path
            # For now, just describe the result
            format_name = "SMT2"

        feedback_prompt = f"""You previously solved this reasoning question:

Question: {question}

Your answer was: {current_result.answer}

Your {format_name} program produced:
- SAT count: {current_result.sat_count}
- UNSAT count: {current_result.unsat_count}

Please critically analyze your solution and identify any potential issues:
1. Is the logical encoding correct?
2. Are all premises properly captured?
3. Are the verification constraints correct?
4. Could the reasoning be improved or made more robust?

If you identify issues, provide specific feedback on how to improve the solution.
If the solution is correct and complete, respond with "No improvement needed."

Provide your analysis and feedback:"""

        try:
            response = llm_client.chat.completions.create(
                model=generator.model,
                messages=[{"role": "user", "content": feedback_prompt}],
                max_completion_tokens=max_tokens,
            )
            feedback = response.choices[0].message.content
            logger.debug(f"[{self.name}] Generated feedback: {feedback[:200]}...")
            return feedback or ""
        except Exception as e:
            logger.error(f"[{self.name}] Error generating feedback: {e}")
            return ""

    def _generate_refined_program(
        self,
        question: str,
        feedback: str,
        previous_result: "QueryResult",
        generator: "Z3ProgramGenerator",
        backend: "Backend",
        cache_dir: str,
        temperature: float,
        max_tokens: int,
    ) -> "QueryResult":
        """Generate refined program using feedback.

        Args:
            question: Original question
            feedback: Feedback from self-critique
            previous_result: Previous QueryResult
            generator: Program generator
            backend: Execution backend
            cache_dir: Directory for caching programs
            temperature: LLM temperature
            max_tokens: Max tokens

        Returns:
            New QueryResult from refined program
        """
        from z3adapter.reasoning.proof_of_thought import QueryResult

        refinement_prompt = f"Based on the following feedback, please revise and improve your solution:\n\n{feedback}"

        try:
            # Generate program with feedback as error trace
            # This reuses the existing feedback mechanism
            gen_result = generator.generate_with_feedback(
                question=question,
                error_trace=refinement_prompt,
                previous_response="",  # We don't have the raw response
                temperature=temperature,
                max_tokens=max_tokens,
            )

            if not gen_result.success or gen_result.program is None:
                logger.warning(f"[{self.name}] Failed to generate refined program")
                return QueryResult(
                    question=question,
                    answer=None,
                    json_program=None,
                    sat_count=0,
                    unsat_count=0,
                    output="",
                    success=False,
                    num_attempts=0,
                    error="Failed to generate refined program",
                )

            # Save and execute refined program
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

            # Execute refined program
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
            logger.error(f"[{self.name}] Error generating refined program: {e}")
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
