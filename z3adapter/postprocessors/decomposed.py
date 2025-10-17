"""Decomposed Prompting postprocessor for breaking down complex questions.

Based on the Decomposed Prompting technique from:
"Decomposed Prompting: A Modular Approach for Solving Complex Tasks" (Khot et al., 2022)
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


class DecomposedPrompting(Postprocessor):
    """Decomposed Prompting for breaking complex questions into sub-questions.

    The Decomposed Prompting technique works by:
    1. Analyzing the complex question and identifying sub-questions
    2. Solving each sub-question independently
    3. Combining sub-question answers to solve the main question

    This is particularly useful for multi-hop reasoning or questions
    that require several logical steps.
    """

    def __init__(self, max_subquestions: int = 5, name: str | None = None):
        """Initialize Decomposed Prompting postprocessor.

        Args:
            max_subquestions: Maximum number of sub-questions to generate
            name: Optional custom name for this postprocessor
        """
        super().__init__(name)
        self.max_subquestions = max_subquestions

    def process(
        self,
        question: str,
        initial_result: "QueryResult",
        generator: "Z3ProgramGenerator",
        backend: "Backend",
        llm_client: Any,
        **kwargs: Any,
    ) -> "QueryResult":
        """Apply Decomposed Prompting to solve the question.

        Args:
            question: Original question
            initial_result: Initial QueryResult
            generator: Program generator
            backend: Execution backend
            llm_client: LLM client
            **kwargs: Additional arguments (cache_dir, temperature, max_tokens)

        Returns:
            QueryResult from decomposed reasoning
        """
        logger.info(f"[{self.name}] Starting decomposed prompting")

        cache_dir = kwargs.get("cache_dir", tempfile.gettempdir())
        temperature = kwargs.get("temperature", 0.1)
        max_tokens = kwargs.get("max_tokens", 16384)

        # Step 1: Decompose question into sub-questions
        sub_questions = self._decompose_question(
            question=question,
            llm_client=llm_client,
            generator=generator,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if not sub_questions:
            logger.warning(f"[{self.name}] Failed to decompose question, using initial result")
            return initial_result

        logger.info(f"[{self.name}] Decomposed into {len(sub_questions)} sub-questions")

        # Step 2: Solve each sub-question
        sub_answers = []
        for i, sub_q in enumerate(sub_questions, 1):
            logger.info(f"[{self.name}] Solving sub-question {i}/{len(sub_questions)}: {sub_q}")

            sub_result = self._solve_subquestion(
                sub_question=sub_q,
                original_question=question,
                generator=generator,
                backend=backend,
                cache_dir=cache_dir,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            if sub_result.success:
                sub_answers.append(
                    {"question": sub_q, "answer": sub_result.answer, "result": sub_result}
                )
                logger.info(f"[{self.name}] Sub-question {i} answer: {sub_result.answer}")
            else:
                logger.warning(f"[{self.name}] Sub-question {i} failed")
                sub_answers.append({"question": sub_q, "answer": None, "result": sub_result})

        # Step 3: Combine sub-answers to answer main question
        final_result = self._combine_answers(
            question=question,
            sub_answers=sub_answers,
            initial_result=initial_result,
            generator=generator,
            backend=backend,
            llm_client=llm_client,
            cache_dir=cache_dir,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        logger.info(
            f"[{self.name}] Decomposed prompting complete. "
            f"Final answer: {final_result.answer}, "
            f"Initial answer: {initial_result.answer}"
        )

        return final_result

    def _decompose_question(
        self,
        question: str,
        llm_client: Any,
        generator: "Z3ProgramGenerator",
        temperature: float,
        max_tokens: int,
    ) -> list[str]:
        """Decompose a complex question into simpler sub-questions.

        Args:
            question: Original complex question
            llm_client: LLM client
            generator: Program generator (for model info)
            temperature: LLM temperature
            max_tokens: Max tokens

        Returns:
            List of sub-questions
        """
        decomposition_prompt = f"""Break down the following complex reasoning question into simpler sub-questions that, when answered together, would help solve the main question.

Main Question: {question}

Please provide 2-{self.max_subquestions} sub-questions that:
1. Are simpler than the main question
2. Can be answered independently or build on each other
3. Together provide the information needed to answer the main question

Format your response as a numbered list:
1. [First sub-question]
2. [Second sub-question]
...

Sub-questions:"""

        try:
            response = llm_client.chat.completions.create(
                model=generator.model,
                messages=[{"role": "user", "content": decomposition_prompt}],
                max_completion_tokens=max_tokens,
            )

            decomposition_text = response.choices[0].message.content or ""

            # Parse numbered list
            sub_questions = []
            for line in decomposition_text.split("\n"):
                # Match patterns like "1. question" or "1) question"
                match = re.match(r"^\s*\d+[\.)]\s*(.+)$", line.strip())
                if match:
                    sub_q = match.group(1).strip()
                    if sub_q:
                        sub_questions.append(sub_q)

            logger.debug(f"[{self.name}] Decomposed into {len(sub_questions)} sub-questions")
            return sub_questions[: self.max_subquestions]

        except Exception as e:
            logger.error(f"[{self.name}] Error decomposing question: {e}")
            return []

    def _solve_subquestion(
        self,
        sub_question: str,
        original_question: str,
        generator: "Z3ProgramGenerator",
        backend: "Backend",
        cache_dir: str,
        temperature: float,
        max_tokens: int,
    ) -> "QueryResult":
        """Solve a single sub-question.

        Args:
            sub_question: The sub-question to solve
            original_question: Original main question (for context)
            generator: Program generator
            backend: Execution backend
            cache_dir: Cache directory
            temperature: LLM temperature
            max_tokens: Max tokens

        Returns:
            QueryResult for the sub-question
        """
        from z3adapter.reasoning.proof_of_thought import QueryResult

        # Add context from original question
        contextualized_question = (
            f"Original question: {original_question}\n\n" f"Sub-question to solve: {sub_question}"
        )

        try:
            # Generate program for sub-question
            gen_result = generator.generate(
                question=contextualized_question,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            if not gen_result.success or gen_result.program is None:
                return QueryResult(
                    question=sub_question,
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
                question=sub_question,
                answer=verify_result.answer,
                json_program=gen_result.json_program,
                sat_count=verify_result.sat_count,
                unsat_count=verify_result.unsat_count,
                output=verify_result.output,
                success=verify_result.success and verify_result.answer is not None,
                num_attempts=1,
            )

        except Exception as e:
            logger.error(f"[{self.name}] Error solving sub-question: {e}")
            return QueryResult(
                question=sub_question,
                answer=None,
                json_program=None,
                sat_count=0,
                unsat_count=0,
                output="",
                success=False,
                num_attempts=0,
                error=str(e),
            )

    def _combine_answers(
        self,
        question: str,
        sub_answers: list[dict[str, Any]],
        initial_result: "QueryResult",
        generator: "Z3ProgramGenerator",
        backend: "Backend",
        llm_client: Any,
        cache_dir: str,
        temperature: float,
        max_tokens: int,
    ) -> "QueryResult":
        """Combine sub-question answers to answer the main question.

        Args:
            question: Main question
            sub_answers: List of sub-question results
            initial_result: Initial result (fallback)
            generator: Program generator
            backend: Execution backend
            llm_client: LLM client
            cache_dir: Cache directory
            temperature: LLM temperature
            max_tokens: Max tokens

        Returns:
            Final QueryResult
        """
        from z3adapter.reasoning.proof_of_thought import QueryResult

        # Build context from sub-answers
        sub_context = "\n".join(
            [
                f"Q: {sa['question']}\nA: {sa['answer']}"
                for sa in sub_answers
                if sa["answer"] is not None
            ]
        )

        if not sub_context:
            logger.warning(f"[{self.name}] No successful sub-answers, using initial result")
            return initial_result

        # Generate final answer using sub-question insights
        combination_prompt = f"""Based on the following sub-question answers, generate a complete solution to the main question.

Main Question: {question}

Sub-question answers:
{sub_context}

Now, create a complete logical program that uses these insights to answer the main question."""

        try:
            gen_result = generator.generate_with_feedback(
                question=question,
                error_trace=combination_prompt,
                previous_response="",
                temperature=temperature,
                max_tokens=max_tokens,
            )

            if not gen_result.success or gen_result.program is None:
                logger.warning(f"[{self.name}] Failed to combine answers, using initial result")
                return initial_result

            # Execute combined program
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
                    f"[{self.name}] Combined answer verification failed, using initial result"
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
            logger.error(f"[{self.name}] Error combining answers: {e}")
            return initial_result
