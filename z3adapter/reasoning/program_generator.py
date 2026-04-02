"""SMT-LIB program generator used by staged-query postprocessors."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from z3adapter.reasoning.smt2_prompt_template import build_smt2_prompt

logger = logging.getLogger(__name__)

BackendType = Literal["smt2"]


@dataclass
class GenerationResult:
    """Result of SMT-LIB program generation."""

    program: str | None
    raw_response: str
    success: bool
    backend: BackendType = "smt2"
    error: str | None = None
    failure_code: str | None = None

    @property
    def smt2_program(self) -> str | None:
        """Return the generated SMT-LIB program."""
        return self.program

    @property
    def program_format(self) -> Literal["smt2"]:
        """Return the serialized program format."""
        return "smt2"


class Z3ProgramGenerator:
    """Generate SMT-LIB programs from natural-language prompts using an LLM."""

    def __init__(self, llm_client: Any, model: str = "gpt-4o", backend: BackendType = "smt2"):
        self.llm_client = llm_client
        self.model = model
        self.backend = backend

    def generate(
        self,
        question: str,
        temperature: float = 0.1,
        max_tokens: int = 16384,
    ) -> GenerationResult:
        """Generate an SMT-LIB program from a question."""
        del temperature
        return self._generate_from_messages(
            messages=[{"role": "user", "content": build_smt2_prompt(question)}],
            max_tokens=max_tokens,
        )

    def generate_with_feedback(
        self,
        question: str,
        error_trace: str,
        previous_response: str,
        temperature: float = 0.1,
        max_tokens: int = 16384,
    ) -> GenerationResult:
        """Regenerate an SMT-LIB program using prior error feedback."""
        del temperature
        feedback_message = (
            f"There was an error processing your response:\n{error_trace}\n"
            "Please fix the SMT-LIB program accordingly."
        )
        return self._generate_from_messages(
            messages=[
                {"role": "user", "content": build_smt2_prompt(question)},
                {"role": "assistant", "content": previous_response},
                {"role": "user", "content": feedback_message},
            ],
            max_tokens=max_tokens,
        )

    def _generate_from_messages(
        self,
        *,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> GenerationResult:
        try:
            response = self.llm_client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=max_tokens,
            )
            raw_response = response.choices[0].message.content or ""
            program = self._extract_smt2(raw_response)
            if program:
                return GenerationResult(program=program, raw_response=raw_response, success=True)

            logger.debug("Raw SMT-LIB generation response:\n%s", raw_response[:1000])
            return GenerationResult(
                program=None,
                raw_response=raw_response,
                success=False,
                error="Failed to extract valid SMT-LIB from response",
                failure_code="program_extraction_failed",
            )
        except Exception as exc:
            logger.error("Error generating SMT-LIB program: %s", exc)
            return GenerationResult(
                program=None,
                raw_response="",
                success=False,
                error=str(exc),
                failure_code="generation_exception",
            )

    def _extract_smt2(self, markdown_content: str) -> str | None:
        """Extract SMT-LIB from markdown or plain text."""
        smt2_pattern = r"```smt2\s*([\s\S]*?)\s*```"
        match = re.search(smt2_pattern, markdown_content)
        if match:
            smt2_text = match.group(1).strip()
            if smt2_text:
                return smt2_text
            logger.error("Found empty SMT-LIB code block")
            return None

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

        logger.error("Could not extract SMT-LIB from response")
        return None
