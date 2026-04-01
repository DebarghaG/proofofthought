"""LLM-driven staged SMT-LIB generator with IR tracking."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

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
        reset_context: bool = True,
    ) -> GenerationResult:
        """
        Generate SMT-LIB program through staged prompting.

        Args:
            text: Natural language text describing the domain/rules
            question: The question to verify
            stages: Optional list of stage names to run (default: all)
            reset_context: Whether to reset the conversion context before generation

        Returns:
            GenerationResult with complete program and context
        """
        if reset_context:
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

    def _canonicalize_symbol(self, symbol: str) -> str:
        """Canonicalize a symbol name for stable SMT-LIB emission."""
        normalized = symbol.strip().replace("-", "_")
        return normalized.lower()

    def _apply_aliases(self, output: str, ctx: ConversionContext) -> str:
        """Rewrite known symbol aliases to their canonical SMT names."""
        if not ctx.symbol_aliases:
            return output

        rewritten = output
        for original, canonical in sorted(
            ctx.symbol_aliases.items(), key=lambda item: -len(item[0])
        ):
            rewritten = re.sub(rf"\b{re.escape(original)}\b", canonical, rewritten)
        return rewritten

    def _extract_forms(self, output: str, command_name: str) -> list[str]:
        """Extract balanced SMT-LIB forms starting with the given command."""
        forms = []
        search_start = 0

        while True:
            match = re.search(rf"\({re.escape(command_name)}\b", output[search_start:])
            if not match:
                break

            start = search_start + match.start()
            depth = 0
            end = start
            for index, char in enumerate(output[start:], start):
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break

            if end > start:
                forms.append(output[start:end])
                search_start = end
            else:
                break

        return forms

    def _format_enum_sort(self, sort_name: str, values: list[str]) -> str:
        """Emit a canonical declare-datatypes block for an enum sort."""
        constructors = " ".join(f"({value})" for value in values)
        return f"(declare-datatypes (({sort_name} 0)) (({constructors})))"

    def _parse_sorts(self, output: str, ctx: ConversionContext) -> None:
        """Parse sort declarations from LLM output."""
        # Match (declare-sort Name 0)
        sort_pattern = r"\(declare-sort\s+(\w+)\s+0\)"
        for match in re.finditer(sort_pattern, output):
            sort_name = match.group(1)
            if sort_name not in ctx.sorts:
                ctx.sorts[sort_name] = SMTSort(
                    name=sort_name,
                    kind=SMTSortKind.UNINTERPRETED,
                    smt_name=sort_name,
                    smt_code=match.group(0),
                    emitted=True,
                )

        for form in self._extract_forms(output, "declare-datatypes"):
            name: str | None = None
            values_str: str | None = None

            full_syntax_match = re.search(
                r"\(declare-datatypes\s+\(\((\w+)\s+0\)\)\s+\(\((.*)\)\)\)\s*$",
                form,
                flags=re.DOTALL,
            )
            if full_syntax_match:
                name = full_syntax_match.group(1)
                values_str = full_syntax_match.group(2)
            else:
                shorthand_match = re.search(
                    r"\(declare-datatypes\s+\(\)\s+\(\((\w+)\s+(.*)\)\)\)\s*$",
                    form,
                    flags=re.DOTALL,
                )
                if shorthand_match:
                    name = shorthand_match.group(1)
                    values_str = shorthand_match.group(2)

            if not name or values_str is None:
                continue

            if "(" in values_str:
                raw_values = re.findall(r"\((\w+)\)", values_str)
                if raw_values and raw_values[0] == name:
                    raw_values = raw_values[1:]
            else:
                raw_values = [value for value in re.findall(r"\b(\w+)\b", values_str) if value]

            canonical_values = []
            for value in raw_values:
                canonical = self._canonicalize_symbol(value)
                ctx.symbol_aliases[value] = canonical
                canonical_values.append(canonical)

            if name not in ctx.sorts:
                ctx.sorts[name] = SMTSort(
                    name=name,
                    kind=SMTSortKind.ENUM,
                    smt_name=name,
                    params={"values": canonical_values},
                    smt_code=self._format_enum_sort(name, canonical_values),
                    emitted=True,
                )

    def _parse_functions(self, output: str, ctx: ConversionContext) -> None:
        """Parse function declarations from LLM output."""
        output = self._apply_aliases(output, ctx)
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
        output = self._apply_aliases(output, ctx)
        # Match (declare-const name Sort)
        const_pattern = r"\(declare-const\s+(\w+)\s+(\w+)\)"
        for match in re.finditer(const_pattern, output):
            name = match.group(1)
            sort = match.group(2)

            enum_values = {
                value
                for enum_sort in ctx.sorts.values()
                if enum_sort.kind == SMTSortKind.ENUM
                for value in enum_sort.params.get("values", [])
            }
            if name in enum_values:
                continue
            if name in ctx.functions or name in ctx.sorts:
                continue

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
        output = self._apply_aliases(output, ctx)
        # Match (assert ...)
        assertions = self._extract_assertions(output)
        for assertion_code in assertions:
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
        output = self._apply_aliases(output, ctx)
        # Parse any new constants
        self._parse_constants(output, ctx)

        # Parse assertions into scenario_assertions
        assertions = self._extract_assertions(output)
        for assertion_code in assertions:
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
        output = self._apply_aliases(output, ctx)
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

    def compose_context_program(
        self,
        *,
        include_scenario: bool = True,
        include_queries: bool = True,
    ) -> str:
        """Compose an SMT-LIB program from the accumulated context."""
        parts = [
            f"(set-logic {self.ctx.logic})",
            "",
        ]

        section_defs: list[tuple[str, list[str]]] = [
            (
                "Sorts",
                [sort.smt_code for sort in self.ctx.sorts.values() if sort.smt_code],
            ),
            (
                "Functions",
                [func.smt_code for func in self.ctx.functions.values() if func.smt_code],
            ),
            (
                "Constants",
                [const.smt_code for const in self.ctx.constants.values() if const.smt_code],
            ),
            (
                "Knowledge Base",
                [
                    assertion.smt_code
                    for assertion in self.ctx.kb_assertions.values()
                    if assertion.smt_code
                ],
            ),
            (
                "Rules",
                [rule.smt_code for rule in self.ctx.rules.values() if rule.smt_code],
            ),
        ]

        if include_scenario:
            section_defs.append(
                (
                    "Scenario",
                    [
                        assertion.smt_code
                        for assertion in self.ctx.scenario_assertions.values()
                        if assertion.smt_code
                    ],
                )
            )

        if include_queries:
            section_defs.append(
                (
                    "Queries",
                    [query.smt_code for query in self.ctx.queries.values() if query.smt_code],
                )
            )

        for section_name, lines in section_defs:
            if not lines:
                continue
            parts.append(f"; --- {section_name} ---")
            parts.extend(lines)
            parts.append("")

        return "\n".join(parts).rstrip()


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
