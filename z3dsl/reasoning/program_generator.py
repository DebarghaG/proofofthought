"""Z3 DSL program generator using LLM."""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from z3dsl.reasoning.structured_program import StructuredProgram

from z3dsl.reasoning.prompt_template import build_prompt

logger = logging.getLogger(__name__)

STRUCTURED_SYSTEM_PROMPT = (
    "You are an assistant that produces Z3 DSL programs. "
    "Always respond with JSON that matches the provided schema."
)


@dataclass
class GenerationResult:
    """Result of JSON program generation."""

    json_program: dict[str, Any] | None
    raw_response: str
    success: bool
    error: str | None = None


class Z3ProgramGenerator:
    """Generate Z3 DSL JSON programs from natural language questions using LLM."""

    def __init__(self, llm_client: Any, model: str = "gpt-4o") -> None:
        """Initialize the program generator.

        Args:
            llm_client: LLM client (OpenAI, Anthropic, etc.)
            model: Model name to use
        """
        self.llm_client = llm_client
        self.model = model

    def generate(
        self,
        question: str,
        temperature: float = 0.1,
        max_tokens: int = 16384,
    ) -> GenerationResult:
        """Generate a Z3 DSL JSON program from a question.

        Args:
            question: Natural language question
            temperature: LLM temperature
            max_tokens: Maximum tokens for response (default 16384 for GPT-5)

        Returns:
            GenerationResult with JSON program or error
        """
        prompt = build_prompt(question)
        messages = self._initial_messages(prompt)

        # Prefer structured outputs when available
        structured_result = self._call_structured_api(messages, temperature, max_tokens)
        if structured_result:
            json_program, raw_response = structured_result
            return GenerationResult(json_program=json_program, raw_response=raw_response, success=True)

        # Fallback to legacy chat completions parsing
        try:
            raw_response = self._call_chat_completion(messages, max_tokens)
        except Exception as exc:
            logger.error(f"Error generating program: {exc}")
            return GenerationResult(
                json_program=None,
                raw_response="",
                success=False,
                error=str(exc),
            )

        json_program = self._extract_json(raw_response)
        if json_program:
            return GenerationResult(json_program=json_program, raw_response=raw_response, success=True)

        logger.debug(f"Raw LLM response:\n{raw_response[:1000]}...")
        return GenerationResult(
            json_program=None,
            raw_response=raw_response,
            success=False,
            error="Failed to extract valid JSON from response",
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
            GenerationResult with corrected JSON program
        """
        prompt = build_prompt(question)
        feedback_message = (
            f"There was an error processing your response:\n{error_trace}\n"
            "Please fix the JSON accordingly."
        )

        messages = self._feedback_messages(prompt, previous_response, feedback_message)

        structured_result = self._call_structured_api(messages, temperature, max_tokens)
        if structured_result:
            json_program, raw_response = structured_result
            return GenerationResult(json_program=json_program, raw_response=raw_response, success=True)

        try:
            raw_response = self._call_chat_completion(messages, max_tokens)
        except Exception as exc:
            logger.error(f"Error generating program with feedback: {exc}")
            return GenerationResult(
                json_program=None,
                raw_response="",
                success=False,
                error=str(exc),
            )

        json_program = self._extract_json(raw_response)
        if json_program:
            return GenerationResult(json_program=json_program, raw_response=raw_response, success=True)

        logger.debug(f"Raw LLM feedback response:\n{raw_response[:1000]}...")
        return GenerationResult(
            json_program=None,
            raw_response=raw_response,
            success=False,
            error="Failed to extract valid JSON from feedback response",
        )

    def _call_structured_api(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple[dict[str, Any], str] | None:
        """Attempt to call the Responses API with structured outputs."""

        responses_api = getattr(self.llm_client, "responses", None)
        parse_fn = getattr(responses_api, "parse", None) if responses_api else None
        if parse_fn is None:
            return None

        try:
            response = parse_fn(
                model=self.model,
                input=messages,
                temperature=temperature,
                max_output_tokens=max_tokens,
                text_format=StructuredProgram,
            )
        except Exception as exc:
            logger.warning(
                "Structured output request failed, falling back to chat completions: %s",
                exc,
            )
            return None

        parsed_program: StructuredProgram | None = getattr(response, "output_parsed", None)
        if parsed_program is None:
            logger.warning("Structured response did not contain parsed output; falling back")
            return None

        json_text = parsed_program.model_dump_json(indent=2, exclude_none=True)
        json_program = parsed_program.to_dsl_dict()
        return json_program, json_text

    def _call_chat_completion(
        self, messages: list[dict[str, str]], max_tokens: int
    ) -> str:
        """Call legacy chat completions API and return raw assistant content."""

        response = self.llm_client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_completion_tokens=max_tokens,
        )
        return response.choices[0].message.content

    def _initial_messages(self, prompt: str) -> list[dict[str, str]]:
        """Construct the initial message sequence used for generation."""

        return [
            {"role": "system", "content": STRUCTURED_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

    def _feedback_messages(
        self, prompt: str, previous_response: str, feedback_message: str
    ) -> list[dict[str, str]]:
        """Construct message sequence when providing feedback to the model."""

        return [
            {"role": "system", "content": STRUCTURED_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": previous_response},
            {"role": "user", "content": feedback_message},
        ]

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
