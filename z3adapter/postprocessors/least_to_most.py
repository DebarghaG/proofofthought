"""Least-to-Most Prompting postprocessor for progressive problem solving.

Based on the Least-to-Most Prompting technique from:
"Least-to-Most Prompting Enables Complex Reasoning in Large Language Models" (Zhou et al., 2022)
"""

import json
import logging
import os
import re
import tempfile
from typing import TYPE_CHECKING, Any

from z3adapter.postprocessors.abstract import Postprocessor

if TYPE_CHECKING:
    from z3adapter.backends.abstract import Backend
    from z3adapter.reasoning.program_generator import Z3ProgramGenerator
    from z3adapter.reasoning.proof_of_thought import QueryResult

logger = logging.getLogger(__name__)


class LeastToMostPrompting(Postprocessor):
    """Least-to-Most Prompting for progressive problem solving.

    The Least-to-Most Prompting technique works by:
    1. Breaking down the problem into a sequence of sub-problems
    2. Ordering sub-problems from simplest to most complex
    3. Solving them sequentially, using solutions from simpler problems
       to inform more complex ones

    This is particularly effective for problems with natural dependencies
    between sub-components.
    """

    def __init__(self, max_steps: int = 5, name: str | None = None):
        """Initialize Least-to-Most Prompting postprocessor.

        Args:
            max_steps: Maximum number of progressive steps
            name: Optional custom name for this postprocessor
        """
        super().__init__(name)
        self.max_steps = max_steps

    def process(
        self,
        question: str,
        initial_result: "QueryResult",
        generator: "Z3ProgramGenerator",
        backend: "Backend",
        llm_client: Any,
        **kwargs: Any,
    ) -> "QueryResult":
        """Apply Least-to-Most Prompting to solve the question.

        Args:
            question: Original question
            initial_result: Initial QueryResult
            generator: Program generator
            backend: Execution backend
            llm_client: LLM client
            **kwargs: Additional arguments (cache_dir, temperature, max_tokens)

        Returns:
            QueryResult from progressive reasoning
        """
        logger.info(f"[{self.name}] Starting least-to-most prompting")

        cache_dir = kwargs.get("cache_dir", tempfile.gettempdir())
        temperature = kwargs.get("temperature", 0.1)
        max_tokens = kwargs.get("max_tokens", 16384)

        # Step 1: Decompose into ordered sub-problems (least to most complex)
        sub_problems = self._decompose_progressive(
            question=question,
            llm_client=llm_client,
            generator=generator,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if not sub_problems:
            logger.warning(
                f"[{self.name}] Failed to decompose into sub-problems, using initial result"
            )
            return initial_result

        logger.info(f"[{self.name}] Decomposed into {len(sub_problems)} progressive steps")

        # Step 2: Solve progressively, building context from previous solutions
        accumulated_context = ""
        progressive_results = []

        for i, sub_problem in enumerate(sub_problems, 1):
            logger.info(
                f"[{self.name}] Solving step {i}/{len(sub_problems)} " f"(complexity level {i})"
            )

            step_result = self._solve_with_context(
                sub_problem=sub_problem,
                original_question=question,
                accumulated_context=accumulated_context,
                generator=generator,
                backend=backend,
                cache_dir=cache_dir,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            progressive_results.append(
                {
                    "step": i,
                    "problem": sub_problem,
                    "result": step_result,
                    "answer": step_result.answer,
                }
            )

            if step_result.success and step_result.answer is not None:
                logger.info(f"[{self.name}] Step {i} answer: {step_result.answer}")
                # Accumulate context for next step
                accumulated_context += f"\n\nStep {i}: {sub_problem}\nAnswer: {step_result.answer}"
            else:
                logger.warning(f"[{self.name}] Step {i} failed, continuing with partial context")
                accumulated_context += f"\n\nStep {i}: {sub_problem}\nAnswer: Unknown (failed)"

        # Step 3: Use all progressive context to answer the final question
        final_result = self._synthesize_final_answer(
            question=question,
            progressive_results=progressive_results,
            accumulated_context=accumulated_context,
            initial_result=initial_result,
            generator=generator,
            backend=backend,
            cache_dir=cache_dir,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        logger.info(
            f"[{self.name}] Least-to-most prompting complete. "
            f"Final answer: {final_result.answer}, "
            f"Initial answer: {initial_result.answer}"
        )

        return final_result

    def _decompose_progressive(
        self,
        question: str,
        llm_client: Any,
        generator: "Z3ProgramGenerator",
        temperature: float,
        max_tokens: int,
    ) -> list[str]:
        """Decompose question into progressive sub-problems (least to most complex).

        Args:
            question: Original question
            llm_client: LLM client
            generator: Program generator (for model info)
            temperature: LLM temperature
            max_tokens: Max tokens

        Returns:
            List of sub-problems ordered from simplest to most complex
        """
        decomposition_prompt = f"""Break down the following complex reasoning question into a progressive sequence of sub-problems, ordered from simplest to most complex.

Main Question: {question}

Please provide 2-{self.max_steps} sub-problems where:
1. Each sub-problem is simpler than the previous one
2. Earlier sub-problems provide foundation for later ones
3. The sequence progresses from basic/simple to complex
4. Together they build up to solving the main question

Format your response as a numbered list from LEAST to MOST complex:
1. [Simplest sub-problem]
2. [Slightly more complex]
3. [Even more complex]
...
{self.max_steps}. [Most complex, close to main question]

Progressive sub-problems:"""

        try:
            response = llm_client.chat.completions.create(
                model=generator.model,
                messages=[{"role": "user", "content": decomposition_prompt}],
                max_completion_tokens=max_tokens,
            )

            decomposition_text = response.choices[0].message.content or ""

            # Parse numbered list
            sub_problems = []
            for line in decomposition_text.split("\n"):
                match = re.match(r"^\s*\d+[\.)]\s*(.+)$", line.strip())
                if match:
                    sub_prob = match.group(1).strip()
                    if sub_prob:
                        sub_problems.append(sub_prob)

            logger.debug(f"[{self.name}] Decomposed into {len(sub_problems)} progressive steps")
            return sub_problems[: self.max_steps]

        except Exception as e:
            logger.error(f"[{self.name}] Error decomposing progressively: {e}")
            return []

    def _solve_with_context(
        self,
        sub_problem: str,
        original_question: str,
        accumulated_context: str,
        generator: "Z3ProgramGenerator",
        backend: "Backend",
        cache_dir: str,
        temperature: float,
        max_tokens: int,
    ) -> "QueryResult":
        """Solve a sub-problem using accumulated context from previous steps.

        Args:
            sub_problem: Current sub-problem to solve
            original_question: Original main question
            accumulated_context: Context from previous steps
            generator: Program generator
            backend: Execution backend
            cache_dir: Cache directory
            temperature: LLM temperature
            max_tokens: Max tokens

        Returns:
            QueryResult for this step
        """
        from z3adapter.reasoning.proof_of_thought import QueryResult

        # Build contextualized question
        if accumulated_context:
            contextualized_question = (
                f"Original question: {original_question}\n\n"
                f"Previous steps solved:{accumulated_context}\n\n"
                f"Current step to solve: {sub_problem}\n\n"
                f"Use insights from previous steps to solve this step."
            )
        else:
            contextualized_question = (
                f"Original question: {original_question}\n\n" f"First step to solve: {sub_problem}"
            )

        try:
            # Generate program for this step
            gen_result = generator.generate(
                question=contextualized_question,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            if not gen_result.success or gen_result.program is None:
                return QueryResult(
                    question=sub_problem,
                    answer=None,
                    json_program=None,
                    sat_count=0,
                    unsat_count=0,
                    output="",
                    success=False,
                    num_attempts=0,
                    error="Failed to generate program",
                )

            # Save and execute
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

            verify_result = backend.execute(program_path)

            # Clean up
            try:
                os.unlink(program_path)
            except Exception:
                pass

            return QueryResult(
                question=sub_problem,
                answer=verify_result.answer,
                json_program=gen_result.json_program,
                sat_count=verify_result.sat_count,
                unsat_count=verify_result.unsat_count,
                output=verify_result.output,
                success=verify_result.success and verify_result.answer is not None,
                num_attempts=1,
            )

        except Exception as e:
            logger.error(f"[{self.name}] Error solving step with context: {e}")
            return QueryResult(
                question=sub_problem,
                answer=None,
                json_program=None,
                sat_count=0,
                unsat_count=0,
                output="",
                success=False,
                num_attempts=0,
                error=str(e),
            )

    def _synthesize_final_answer(
        self,
        question: str,
        progressive_results: list[dict[str, Any]],
        accumulated_context: str,
        initial_result: "QueryResult",
        generator: "Z3ProgramGenerator",
        backend: "Backend",
        cache_dir: str,
        temperature: float,
        max_tokens: int,
    ) -> "QueryResult":
        """Synthesize final answer using all progressive context.

        Args:
            question: Main question
            progressive_results: Results from all progressive steps
            accumulated_context: Full accumulated context
            initial_result: Initial result (fallback)
            generator: Program generator
            backend: Execution backend
            cache_dir: Cache directory
            temperature: LLM temperature
            max_tokens: Max tokens

        Returns:
            Final QueryResult
        """
        from z3adapter.reasoning.proof_of_thought import QueryResult

        # Check if we have any successful steps
        successful_steps = [r for r in progressive_results if r["result"].success]
        if not successful_steps:
            logger.warning(f"[{self.name}] No successful steps, using initial result")
            return initial_result

        # Generate final answer using progressive insights
        synthesis_prompt = f"""Using the progressive reasoning steps below, generate a complete solution to the main question.

Main Question: {question}

Progressive reasoning (from simplest to most complex):{accumulated_context}

Now create a complete logical program that synthesizes these progressive insights to answer the main question comprehensively."""

        try:
            gen_result = generator.generate_with_feedback(
                question=question,
                error_trace=synthesis_prompt,
                previous_response="",
                temperature=temperature,
                max_tokens=max_tokens,
            )

            if not gen_result.success or gen_result.program is None:
                logger.warning(
                    f"[{self.name}] Failed to synthesize final answer, using initial result"
                )
                return initial_result

            # Execute synthesized program
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

            verify_result = backend.execute(program_path)

            # Clean up
            try:
                os.unlink(program_path)
            except Exception:
                pass

            if not verify_result.success or verify_result.answer is None:
                logger.warning(
                    f"[{self.name}] Synthesized answer verification failed, using initial result"
                )
                return initial_result

            return QueryResult(
                question=question,
                answer=verify_result.answer,
                json_program=gen_result.json_program,
                sat_count=verify_result.sat_count,
                unsat_count=verify_result.unsat_count,
                output=verify_result.output,
                success=True,
                num_attempts=1,
            )

        except Exception as e:
            logger.error(f"[{self.name}] Error synthesizing final answer: {e}")
            return initial_result
