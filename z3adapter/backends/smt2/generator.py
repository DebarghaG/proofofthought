"""LLM-driven staged SMT-LIB generator with IR tracking."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from z3adapter.backends.smt2.ir import (
    ConversionContext,
    SMTAssertion,
    SMTConstant,
    SMTFunction,
    SMTQuery,
    SMTSort,
    SMTSortKind,
)
from z3adapter.backends.smt2.prompts import (
    format_constants_prompt,
    format_full_context,
    format_functions_prompt,
    format_kb_prompt,
    format_query_prompt,
    format_scenario_prompt,
    format_sorts_prompt,
)

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """Protocol for LLM client interface."""

    def generate(self, prompt: str) -> str:
        """Generate text from prompt."""
        ...


@dataclass
class GenerationStage:
    """Represents a stage in the generation pipeline."""

    name: str
    prompt_formatter: Callable[[str, ConversionContext], str]
    parser: Callable[[str, ConversionContext], None]
    requires_question: bool = False  # Some stages need the question, not just text


@dataclass
class GenerationResult:
    """Result of the staged generation process."""

    success: bool
    smt2_program: str
    context: ConversionContext
    stage_outputs: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class StagedGenerator:
    """
    Orchestrates multi-stage LLM generation of SMT-LIB programs.

    Each stage:
    1. Formats a prompt with current IR context
    2. Calls LLM to generate SMT-LIB fragment
    3. Parses output and updates IR
    4. Passes updated context to next stage
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client
        self.ctx = ConversionContext()

    def generate(
        self,
        text: str,
        question: str,
        stages: list[str] | None = None,
    ) -> GenerationResult:
        """
        Generate SMT-LIB program through staged prompting.

        Args:
            text: Natural language text describing the domain/rules
            question: The question to verify
            stages: Optional list of stage names to run (default: all)

        Returns:
            GenerationResult with complete program and context
        """
        self.ctx = ConversionContext()
        stage_outputs: dict[str, str] = {}
        errors: list[str] = []

        # Define the stages
        all_stages = [
            GenerationStage("sorts", format_sorts_prompt, self._parse_sorts),
            GenerationStage("functions", format_functions_prompt, self._parse_functions),
            GenerationStage("constants", format_constants_prompt, self._parse_constants),
            GenerationStage("knowledge_base", format_kb_prompt, self._parse_kb),
            GenerationStage(
                "scenario",
                lambda q, ctx: format_scenario_prompt(q, ctx),
                self._parse_scenario,
                requires_question=True,
            ),
            GenerationStage(
                "query",
                lambda q, ctx: format_query_prompt(q, ctx),
                self._parse_query,
                requires_question=True,
            ),
        ]

        # Filter stages if specified
        if stages:
            all_stages = [s for s in all_stages if s.name in stages]

        # Run each stage
        for stage in all_stages:
            try:
                # Format prompt with appropriate input
                if stage.requires_question:
                    prompt = stage.prompt_formatter(question, self.ctx)
                else:
                    prompt = stage.prompt_formatter(text, self.ctx)

                logger.info(f"Running stage: {stage.name}")
                logger.debug(f"Prompt:\n{prompt}")

                # Call LLM
                output = self.llm_client.generate(prompt)
                logger.debug(f"Output:\n{output}")

                # Clean output (remove markdown code blocks if present)
                output = self._clean_output(output)

                # Parse and update context
                stage.parser(output, self.ctx)

                stage_outputs[stage.name] = output

            except Exception as e:
                error_msg = f"Stage '{stage.name}' failed: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        # Compose final program
        smt2_program = self._compose_program(stage_outputs)

        return GenerationResult(
            success=len(errors) == 0,
            smt2_program=smt2_program,
            context=self.ctx,
            stage_outputs=stage_outputs,
            errors=errors,
        )

    def _clean_output(self, output: str) -> str:
        """Remove markdown code blocks and clean LLM output."""
        # Remove ```smt2 or ``` code blocks
        output = re.sub(r"```(?:smt2?)?\s*", "", output)
        output = re.sub(r"```\s*$", "", output)
        # Remove leading/trailing whitespace
        return output.strip()

    def _parse_sorts(self, output: str, ctx: ConversionContext) -> None:
        """Parse sort declarations from LLM output."""
        # Match (declare-sort Name 0)
        sort_pattern = r"\(declare-sort\s+(\w+)\s+0\)"
        for match in re.finditer(sort_pattern, output):
            name = match.group(1)
            if name not in ctx.sorts:
                ctx.sorts[name] = SMTSort(
                    name=name,
                    kind=SMTSortKind.UNINTERPRETED,
                    smt_name=name,
                    smt_code=match.group(0),
                    emitted=True,
                )

        # Match (declare-datatypes ((Name 0)) (((Name (v1) (v2)...))))
        enum_pattern = r"\(declare-datatypes\s+\(\((\w+)\s+0\)\)\s+\(\(\((\w+)\s+((?:\(\w+\)\s*)+)\)\)\)\)"
        for match in re.finditer(enum_pattern, output):
            name = match.group(1)
            values_str = match.group(3)
            values = re.findall(r"\((\w+)\)", values_str)
            if name not in ctx.sorts:
                ctx.sorts[name] = SMTSort(
                    name=name,
                    kind=SMTSortKind.ENUM,
                    smt_name=name,
                    params={"values": values},
                    smt_code=match.group(0),
                    emitted=True,
                )

    def _parse_functions(self, output: str, ctx: ConversionContext) -> None:
        """Parse function declarations from LLM output."""
        # Match (declare-fun name (Sort1 Sort2) RetSort)
        func_pattern = r"\(declare-fun\s+(\w+)\s+\(([^)]*)\)\s+(\w+)\)"
        for match in re.finditer(func_pattern, output):
            name = match.group(1)
            domain_str = match.group(2).strip()
            range_sort = match.group(3)

            domain = domain_str.split() if domain_str else []

            if name not in ctx.functions:
                ctx.functions[name] = SMTFunction(
                    name=name,
                    smt_name=name,
                    domain=domain,
                    range_sort=range_sort,
                    smt_code=match.group(0),
                    emitted=True,
                )

    def _parse_constants(self, output: str, ctx: ConversionContext) -> None:
        """Parse constant declarations from LLM output."""
        # Match (declare-const name Sort)
        const_pattern = r"\(declare-const\s+(\w+)\s+(\w+)\)"
        for match in re.finditer(const_pattern, output):
            name = match.group(1)
            sort = match.group(2)

            if name not in ctx.constants:
                ctx.constants[name] = SMTConstant(
                    name=name,
                    smt_name=name,
                    sort=sort,
                    smt_code=match.group(0),
                    emitted=True,
                )

    def _parse_kb(self, output: str, ctx: ConversionContext) -> None:
        """Parse knowledge base assertions from LLM output."""
        # Match (assert ...)
        assertions = self._extract_assertions(output)
        for i, assertion_code in enumerate(assertions):
            assertion_id = f"kb_{len(ctx.kb_assertions)}"
            ctx.kb_assertions[assertion_id] = SMTAssertion(
                id=assertion_id,
                dsl_expr="",  # Not from DSL
                smt_expr=assertion_code,
                smt_code=assertion_code,
                emitted=True,
            )

    def _parse_scenario(self, output: str, ctx: ConversionContext) -> None:
        """Parse scenario setup from LLM output."""
        # Parse any new constants
        self._parse_constants(output, ctx)

        # Parse assertions into scenario_assertions
        assertions = self._extract_assertions(output)
        for i, assertion_code in enumerate(assertions):
            assertion_id = f"scenario_{len(ctx.scenario_assertions)}"
            ctx.scenario_assertions[assertion_id] = SMTAssertion(
                id=assertion_id,
                dsl_expr="",
                smt_expr=assertion_code,
                smt_code=assertion_code,
                emitted=True,
            )

    def _parse_query(self, output: str, ctx: ConversionContext) -> None:
        """Parse query from LLM output."""
        query_id = f"query_{len(ctx.queries)}"
        ctx.queries[query_id] = SMTQuery(
            id=query_id,
            name="verification",
            assertions=[],
            smt_code=output,
            emitted=True,
        )

    def _extract_assertions(self, output: str) -> list[str]:
        """Extract (assert ...) expressions from output."""
        assertions = []
        i = 0
        while i < len(output):
            # Find (assert
            match = re.search(r"\(assert\s+", output[i:])
            if not match:
                break

            start = i + match.start()
            # Find matching closing paren
            depth = 0
            end = start
            for j, char in enumerate(output[start:], start):
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        end = j + 1
                        break

            if end > start:
                assertions.append(output[start:end])
                i = end
            else:
                break

        return assertions

    def _compose_program(self, stage_outputs: dict[str, str]) -> str:
        """Compose the final SMT-LIB program from stage outputs."""
        parts = [
            "(set-logic ALL)",
            "",
        ]

        # Add each stage's output in order
        stage_order = ["sorts", "functions", "constants", "knowledge_base", "scenario", "query"]

        for stage_name in stage_order:
            if stage_name in stage_outputs:
                output = stage_outputs[stage_name].strip()
                if output:
                    parts.append(f"; --- {stage_name.replace('_', ' ').title()} ---")
                    parts.append(output)
                    parts.append("")

        return "\n".join(parts)

    def get_context(self) -> ConversionContext:
        """Get the current conversion context."""
        return self.ctx

    def get_context_summary(self) -> str:
        """Get a summary of the context for debugging/display."""
        return format_full_context(self.ctx)


class SimpleLLMClient:
    """Simple LLM client wrapper for testing/integration."""

    def __init__(self, generate_fn: Callable[[str], str]) -> None:
        """
        Initialize with a generation function.

        Args:
            generate_fn: Function that takes prompt and returns generated text
        """
        self._generate_fn = generate_fn

    def generate(self, prompt: str) -> str:
        """Generate text from prompt."""
        return self._generate_fn(prompt)
