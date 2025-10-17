"""Z3 DSL program generator using LLM."""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from z3adapter.reasoning.prompt_template import build_prompt
from z3adapter.reasoning.smt2_prompt_template import build_smt2_prompt

logger = logging.getLogger(__name__)

BackendType = Literal["json", "smt2"]


@dataclass
class GenerationResult:
    """Result of program generation."""

    program: dict[str, Any] | str | None  # JSON dict or SMT2 string
    raw_response: str
    success: bool
    backend: BackendType
    error: str | None = None

    # Backward compatibility
    @property
    def json_program(self) -> dict[str, Any] | None:
        """Get JSON program (for backward compatibility)."""
        if self.backend == "json" and isinstance(self.program, dict):
            return self.program
        return None

    @property
    def smt2_program(self) -> str | None:
        """Get SMT2 program text."""
        if self.backend == "smt2" and isinstance(self.program, str):
            return self.program
        return None


class Z3ProgramGenerator:
    """Generate Z3 DSL programs from natural language questions using LLM."""

    def __init__(
        self, llm_client: Any, model: str = "gpt-4o", backend: BackendType = "smt2"
    ) -> None:
        """Initialize the program generator.

        Args:
            llm_client: LLM client (OpenAI, Anthropic, etc.)
            model: Model name to use
            backend: Backend type ("json" or "smt2")
        """
        self.llm_client = llm_client
        self.model = model
        self.backend = backend

    def generate(
        self,
        question: str,
        temperature: float = 0.1,
        max_tokens: int = 16384,
    ) -> GenerationResult:
        """Generate a Z3 DSL program from a question.

        Args:
            question: Natural language question
            temperature: LLM temperature
            max_tokens: Maximum tokens for response (default 16384 for GPT-5)

        Returns:
            GenerationResult with program or error
        """
        try:
            # Select prompt based on backend
            if self.backend == "json":
                prompt = build_prompt(question)
            else:  # smt2
                prompt = build_smt2_prompt(question)

            # Make LLM API call (compatible with both OpenAI and Azure OpenAI)
            # Azure OpenAI requires content as string, not list
            # GPT-5 only supports temperature=1 (default), so don't pass it
            response = self.llm_client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=max_tokens,
            )

            raw_response = response.choices[0].message.content

            # Extract program based on backend
            if self.backend == "json":
                program: dict[str, Any] | str | None = self._extract_json(raw_response)
                error_msg = "Failed to extract valid JSON from response"
            else:  # smt2
                program = self._extract_smt2(raw_response)
                error_msg = "Failed to extract valid SMT2 from response"

            if program:
                return GenerationResult(
                    program=program,
                    raw_response=raw_response,
                    success=True,
                    backend=self.backend,
                )
            else:
                # Log the raw response to help debug extraction failures
                logger.debug(f"Raw LLM response:\n{raw_response[:1000]}...")
                return GenerationResult(
                    program=None,
                    raw_response=raw_response,
                    success=False,
                    backend=self.backend,
                    error=error_msg,
                )

        except Exception as e:
            logger.error(f"Error generating program: {e}")
            return GenerationResult(
                program=None,
                raw_response="",
                success=False,
                backend=self.backend,
                error=str(e),
            )

    def generate_with_feedback(
        self,
        question: str,
        error_trace: str,
        previous_response: str,
        temperature: float = 0.1,
        max_tokens: int = 16384,
    ) -> GenerationResult:
        """Regenerate program with error feedback.

        Args:
            question: Original question
            error_trace: Error message from previous attempt
            previous_response: Previous LLM response
            temperature: LLM temperature
            max_tokens: Maximum tokens (default 16384 for GPT-5)

        Returns:
            GenerationResult with corrected program
        """
        try:
            # Select prompt based on backend
            if self.backend == "json":
                prompt = build_prompt(question)
                format_msg = "Please fix the JSON accordingly."
            else:  # smt2
                prompt = build_smt2_prompt(question)
                format_msg = "Please fix the SMT2 program accordingly."

            feedback_message = (
                f"There was an error processing your response:\n{error_trace}\n{format_msg}"
            )

            # Multi-turn conversation with error feedback
            # Compatible with both OpenAI and Azure OpenAI
            # GPT-5 only supports temperature=1 (default), so don't pass it
            response = self.llm_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": previous_response},
                    {"role": "user", "content": feedback_message},
                ],
                max_completion_tokens=max_tokens,
            )

            raw_response = response.choices[0].message.content

            # Extract program based on backend
            if self.backend == "json":
                program: dict[str, Any] | str | None = self._extract_json(raw_response)
                error_msg = "Failed to extract valid JSON from feedback response"
            else:  # smt2
                program = self._extract_smt2(raw_response)
                error_msg = "Failed to extract valid SMT2 from feedback response"

            if program:
                return GenerationResult(
                    program=program,
                    raw_response=raw_response,
                    success=True,
                    backend=self.backend,
                )
            else:
                # Log the raw response to help debug extraction failures
                logger.debug(f"Raw LLM feedback response:\n{raw_response[:1000]}...")
                return GenerationResult(
                    program=None,
                    raw_response=raw_response,
                    success=False,
                    backend=self.backend,
                    error=error_msg,
                )

        except Exception as e:
            logger.error(f"Error generating program with feedback: {e}")
            return GenerationResult(
                program=None,
                raw_response="",
                success=False,
                backend=self.backend,
                error=str(e),
            )

    def _extract_json(self, markdown_content: str) -> dict[str, Any] | None:
        """Extract JSON from markdown code block.

        Args:
            markdown_content: Markdown text potentially containing JSON

        Returns:
            Parsed JSON dict or None if extraction failed
        """
        # Pattern to match ```json ... ``` code blocks
        json_pattern = r"```json\s*(\{[\s\S]*?\})\s*```"
        match = re.search(json_pattern, markdown_content)

        if match:
            try:
                json_str = match.group(1)
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON: {e}")
                return None

        # Try to find JSON without code block markers
        try:
            # Look for { ... } pattern
            brace_pattern = r"\{[\s\S]*\}"
            match = re.search(brace_pattern, markdown_content)
            if match:
                return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

        return None

    def _extract_smt2(self, markdown_content: str) -> str | None:
        """Extract SMT2 from markdown code block.

        Args:
            markdown_content: Markdown text potentially containing SMT2

        Returns:
            SMT2 program text or None if extraction failed
        """
        # Pattern to match ```smt2 ... ``` code blocks
        smt2_pattern = r"```smt2\s*([\s\S]*?)\s*```"
        match = re.search(smt2_pattern, markdown_content)

        if match:
            smt2_text = match.group(1).strip()
            if smt2_text:
                return smt2_text
            logger.error("Found empty SMT2 code block")
            return None

        # Try to find SMT2 without code block markers (starts with comment or paren)
        # Look for lines that start with ';' or '('
        lines = markdown_content.split("\n")
        smt2_lines = []
        in_smt2 = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith(";") or stripped.startswith("("):
                in_smt2 = True
            if in_smt2:
                smt2_lines.append(line)

        if smt2_lines:
            return "\n".join(smt2_lines).strip()

        logger.error("Could not extract SMT2 from response")
        return None
