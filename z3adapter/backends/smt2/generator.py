"""LLM-driven staged SMT-LIB generator with IR tracking.

The generator is intentionally SMT-only: the model emits SMT-LIB fragments, not a
typed JSON IR. The non-obvious normalization and validation logic below exists
because benchmark runs surfaced recurring failure modes that were cheap to fix in
code and expensive to keep re-solving in prompts:

- models sometimes echo full-program commands like ``set-logic`` into a stage
- zero-arity symbols are often emitted as ``declare-fun`` instead of ``declare-const``
- declarations occasionally spill into the knowledge-base or scenario stages
- identity relations such as ``same_as`` are emitted as plain predicates, which
  leaves the solver unable to substitute equal entities in downstream queries

The design here is therefore:

1. every stage sees the full accumulated world model
2. stage output is normalized and validated before mutating shared context
3. repairs happen at the failing stage before we fall back to full-program repair
4. the final executable program is composed from the validated context, not by
   blindly concatenating raw model output
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

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
    BACKGROUND_KNOWLEDGE_COMMENT,
    format_constants_prompt,
    format_full_context,
    format_functions_prompt,
    format_kb_prompt,
    format_query_prompt,
    format_scenario_prompt,
    format_sorts_prompt,
    format_world_model_smt,
)

logger = logging.getLogger(__name__)

# These commands are valid SMT-LIB, but they are not meaningful stage output.
# They commonly appear when the model regurgitates a whole program during a
# single-stage repair, so we strip them before validation.
NON_STAGE_COMMANDS = {
    "set-logic",
    "set-option",
    "check-sat",
    "get-model",
    "get-value",
    "push",
    "pop",
}
# Identity predicates are often emitted as ordinary relations in natural-language
# entailment tasks. We treat a small allowlist as semantic equality so the solver
# can actually propagate facts across aliases.
IDENTITY_RELATION_NAMES = {
    "same_as",
    "sameas",
    "is_same_as",
    "same_entity",
    "same_entity_as",
    "is_same_entity",
    "identical_to",
    "equals",
}

STAGE_ORDER: tuple[str, ...] = (
    "sorts",
    "functions",
    "constants",
    "knowledge_base",
    "scenario",
    "query",
)
VerificationMode = Literal["entailment", "consistency"]


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
    1. Formats a prompt with current IR context and full world-model SMT
    2. Calls the LLM to generate an SMT-LIB fragment
    3. Normalizes and validates that fragment before shared state is updated
    4. Repairs only the failing stage if validation or parsing breaks
    5. Passes the updated context to the next stage
    """

    def __init__(
        self,
        llm_client: LLMClient,
        verification_mode: VerificationMode = "entailment",
        max_stage_repairs: int = 1,
        allow_background_knowledge: bool = False,
        require_background_knowledge_tags: bool = False,
    ) -> None:
        self.llm_client = llm_client
        self.ctx = ConversionContext()
        self.verification_mode = verification_mode
        self.max_stage_repairs = max(0, max_stage_repairs)
        self.allow_background_knowledge = allow_background_knowledge
        self.require_background_knowledge_tags = require_background_knowledge_tags

    def _all_stages(self) -> list[GenerationStage]:
        """Return the canonical stage definitions."""
        return [
            GenerationStage(
                "sorts",
                lambda text, ctx: format_sorts_prompt(
                    text,
                    ctx,
                    allow_background_knowledge=self.allow_background_knowledge,
                ),
                self._parse_sorts,
            ),
            GenerationStage(
                "functions",
                lambda text, ctx: format_functions_prompt(
                    text,
                    ctx,
                    allow_background_knowledge=self.allow_background_knowledge,
                ),
                self._parse_functions,
            ),
            GenerationStage(
                "constants",
                lambda text, ctx: format_constants_prompt(
                    text,
                    ctx,
                    allow_background_knowledge=self.allow_background_knowledge,
                ),
                self._parse_constants,
            ),
            GenerationStage(
                "knowledge_base",
                lambda text, ctx: format_kb_prompt(
                    text,
                    ctx,
                    allow_background_knowledge=self.allow_background_knowledge,
                ),
                self._parse_kb,
            ),
            GenerationStage(
                "scenario",
                lambda q, ctx: format_scenario_prompt(
                    q,
                    ctx,
                    allow_background_knowledge=self.allow_background_knowledge,
                ),
                self._parse_scenario,
                requires_question=True,
            ),
            GenerationStage(
                "query",
                lambda q, ctx: format_query_prompt(
                    q,
                    ctx,
                    self.verification_mode,
                    allow_background_knowledge=self.allow_background_knowledge,
                ),
                self._parse_query,
                requires_question=True,
            ),
        ]

    def set_context(self, context: ConversionContext) -> None:
        """Replace the current conversion context."""
        self.ctx = context

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
        all_stages = self._all_stages()

        # Filter stages if specified
        if stages:
            all_stages = [s for s in all_stages if s.name in stages]

        # Run each stage
        for stage in all_stages:
            try:
                # Format prompt with appropriate input
                stage_input = question if stage.requires_question else text
                prompt = stage.prompt_formatter(stage_input, self.ctx)

                logger.info(f"Running stage: {stage.name}")
                logger.debug(f"Prompt:\n{prompt}")

                output = self._run_stage(stage, prompt, stage_input)

                stage_outputs[stage.name] = output

            except Exception as e:
                error_msg = f"Stage '{stage.name}' failed: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        smt2_program = self.compose_context_program(
            include_scenario=bool(stage_outputs.get("scenario")),
            include_queries=bool(stage_outputs.get("query")),
        )

        return GenerationResult(
            success=len(errors) == 0,
            smt2_program=smt2_program,
            context=self.ctx,
            stage_outputs=stage_outputs,
            errors=errors,
        )

    def rebuild_context_from_outputs(
        self,
        stage_outputs: dict[str, str],
        *,
        through_stage: str | None = None,
    ) -> ConversionContext:
        """Rebuild the conversion context by replaying saved stage outputs."""
        self.ctx = ConversionContext()
        for stage in self._all_stages():
            output = stage_outputs.get(stage.name, "")
            if output:
                prepared_output = self._prepare_stage_output(
                    stage.name,
                    self._clean_output(output),
                    self.ctx,
                )
                stage.parser(prepared_output, self.ctx)
            if through_stage and stage.name == through_stage:
                break
        return self.ctx

    def _run_stage(
        self,
        stage: GenerationStage,
        prompt: str,
        stage_input: str,
    ) -> str:
        """Generate, validate, and parse a single stage with local repairs."""
        attempt_prompt = prompt
        last_error: Exception | None = None

        for attempt in range(self.max_stage_repairs + 1):
            logger.info("Running stage %s attempt %d", stage.name, attempt + 1)
            raw_output = self.llm_client.generate(attempt_prompt)
            logger.debug("Raw stage output for %s:\n%s", stage.name, raw_output)

            cleaned_output = self._clean_output(raw_output)
            candidate_ctx = copy.deepcopy(self.ctx)

            try:
                prepared_output = self._prepare_stage_output(
                    stage.name,
                    cleaned_output,
                    candidate_ctx,
                )
                stage.parser(prepared_output, candidate_ctx)
            except Exception as exc:  # pragma: no cover - covered via caller behavior
                last_error = exc
                if attempt >= self.max_stage_repairs:
                    raise
                logger.warning(
                    "Stage %s failed validation or parsing on attempt %d: %s",
                    stage.name,
                    attempt + 1,
                    exc,
                )
                attempt_prompt = self._format_stage_repair_prompt(
                    stage_name=stage.name,
                    base_prompt=prompt,
                    stage_input=stage_input,
                    failed_output=cleaned_output,
                    error=str(exc),
                )
                continue

            self.ctx = candidate_ctx
            return prepared_output

        if last_error is None:  # pragma: no cover - defensive
            raise RuntimeError(f"Stage {stage.name} failed without reporting an error")
        raise last_error

    def _clean_output(self, output: str) -> str:
        """Remove markdown code blocks and clean LLM output."""
        # Remove ```smt2 or ``` code blocks
        output = re.sub(r"```(?:smt2?)?\s*", "", output)
        output = re.sub(r"```\s*$", "", output)
        # Remove leading/trailing whitespace
        return output.strip()

    def _prepare_stage_output(
        self,
        stage_name: str,
        output: str,
        ctx: ConversionContext,
    ) -> str:
        """Normalize and validate raw stage output before parsing.

        This is the main guardrail against "almost correct" stage output. The
        work here is not cosmetic: it turns benchmark-specific recurrent model
        mistakes into deterministic rewrites so we do not keep paying for the
        same repair in later stages or at solver time.
        """
        normalized = self._normalize_stage_output(stage_name, output, ctx)
        self._validate_stage_output(stage_name, normalized, ctx)
        return normalized

    def _normalize_query_formula(self, output: str) -> tuple[str, str | None]:
        """Extract one SMT-LIB boolean formula from model output."""
        description: str | None = None
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith(";"):
                comment = stripped[1:].strip()
                if comment.lower().startswith("query:"):
                    description = comment.split(":", 1)[1].strip() or None
                    break

        assert_forms = self._extract_forms(output, "assert")
        if assert_forms:
            first_assert = assert_forms[0]
            match = re.match(r"\(assert\s+(.*)\)\s*$", first_assert, flags=re.DOTALL)
            if not match:
                raise ValueError("Could not normalize SMT-LIB assert form from query stage")
            return match.group(1).strip(), description

        command_patterns = [
            r"\(push\b[^)]*\)",
            r"\(pop\b[^)]*\)",
            r"\(check-sat\b[^)]*\)",
            r"\(get-model\b[^)]*\)",
            r"\(get-value\b[^)]*\)",
        ]
        formula = output
        for pattern in command_patterns:
            formula = re.sub(pattern, "", formula)

        formula = re.sub(r"(?m)^\s*;.*$", "", formula).strip()
        if not formula:
            raise ValueError("Query stage did not emit a boolean SMT-LIB formula")
        return formula, description

    def _normalize_stage_output(
        self,
        stage_name: str,
        output: str,
        ctx: ConversionContext,
    ) -> str:
        """Apply safe, stage-aware SMT-LIB rewrites before validation.

        The important principle is that we only rewrite patterns whose intended
        meaning is already clear. We do not try to "invent" semantics here; we
        only recover from formatting and stage-placement mistakes.
        """
        normalized = output.strip()
        if not normalized:
            return normalized

        if normalized.upper() in {
            "NONE",
            "(NONE)",
            "(none)",
            "NO NEW ASSERTIONS",
            "NO ADDITIONAL ASSERTIONS",
            "NO SCENARIO FACTS",
            "NO SCENARIO ASSERTIONS",
        }:
            return ""

        normalized = re.sub(
            r"\(declare-fun\s+(\w+)\s+\(\s*\)\s+([A-Za-z_][\w]*)\)",
            r"(declare-const \1 \2)",
            normalized,
        )
        normalized = re.sub(
            r"\(declare-fun\s+(\w+)\s+([A-Za-z_][\w]*)\)",
            r"(declare-const \1 \2)",
            normalized,
        )

        if stage_name != "query":
            normalized = self._strip_non_stage_commands(normalized)
            normalized = self._retain_relevant_forms(normalized)

        if stage_name in {"knowledge_base", "scenario", "query"}:
            normalized = self._unwrap_zero_arity_applications(normalized, ctx)

        return normalized.strip()

    def _validate_stage_output(
        self,
        stage_name: str,
        output: str,
        ctx: ConversionContext,
    ) -> None:
        """Reject stage outputs that violate the staged SMT contract.

        Validation is intentionally performed against a transient copy of the
        context so declarations emitted earlier in the same stage can satisfy
        later forms without mutating the real context until the whole stage is
        known-good.
        """
        if not output:
            return

        if stage_name == "query":
            self._validate_query_output(output)
            return

        if (
            self.require_background_knowledge_tags
            and stage_name in {"knowledge_base", "scenario"}
        ):
            self._validate_background_knowledge_tags(stage_name, output)

        forms = self._extract_top_level_forms(output)

        allowed_commands = {
            "sorts": {"declare-sort", "declare-datatypes"},
            "functions": {"declare-sort", "declare-datatypes", "declare-fun", "declare-const"},
            "constants": {"declare-sort", "declare-datatypes", "declare-fun", "declare-const"},
            "knowledge_base": {
                "declare-sort",
                "declare-datatypes",
                "declare-fun",
                "declare-const",
                "assert",
            },
            "scenario": {"declare-sort", "declare-datatypes", "declare-fun", "declare-const", "assert"},
        }.get(stage_name, set())

        if not forms:
            raise ValueError(f"Stage '{stage_name}' did not emit any SMT-LIB forms")

        transient_ctx = copy.deepcopy(ctx)
        for form in forms:
            command_name = self._command_name(form)
            if command_name not in allowed_commands:
                raise ValueError(
                    f"Stage '{stage_name}' emitted unsupported command '{command_name}'"
                )
            self._validate_form_against_context(stage_name, form, transient_ctx)
            self._apply_form_to_validation_context(form, transient_ctx)

    def _validate_query_output(self, output: str) -> None:
        """Ensure the query stage emits a single boolean formula, not solver commands."""
        banned_commands = (
            "declare-sort",
            "declare-datatypes",
            "declare-fun",
            "declare-const",
            "set-logic",
            "check-sat",
            "get-model",
            "push",
            "pop",
        )
        for command in banned_commands:
            if re.search(rf"\({re.escape(command)}\b", output):
                raise ValueError(
                    f"Query stage emitted a solver or declaration command '{command}' instead of a formula"
                )

        formula, _ = self._normalize_query_formula(output)

        if formula.lstrip().startswith("("):
            forms = self._extract_top_level_forms(formula)
            residual = self._strip_comments(formula)
            for form in forms:
                residual = residual.replace(form, "", 1)
            if len(forms) != 1 or residual.strip():
                raise ValueError("Query stage must emit exactly one boolean SMT-LIB formula")
            return

        if not re.fullmatch(r"[^\s()]+", formula):
            raise ValueError("Query stage must emit exactly one boolean SMT-LIB formula")

    def _validate_background_knowledge_tags(self, stage_name: str, output: str) -> None:
        """Require explicit provenance tags for assertion-bearing stages.

        In knowledge-only mode we do not let the model silently "upgrade" its
        own common-sense facts into apparently grounded premises. Requiring the
        exact comment marker here turns tag compliance into a normal staged
        repair problem instead of a late execution-time failure.
        """
        assertion_entries = self._extract_assertion_entries(output)
        if not assertion_entries:
            return
        untagged_assertions = [
            assertion_code
            for assertion_code, has_tag in assertion_entries
            if not has_tag
        ]
        if untagged_assertions:
            raise ValueError(
                f"Stage '{stage_name}' emitted assertions without the required "
                f"`{BACKGROUND_KNOWLEDGE_COMMENT}` comment. "
                "When there is no external grounding, place that exact comment on the "
                "line immediately above every asserted fact or rule."
            )

    def _validate_form_against_context(
        self,
        stage_name: str,
        form: str,
        ctx: ConversionContext,
    ) -> None:
        """Perform lightweight stage-aware semantic validation."""
        del stage_name
        command_name = self._command_name(form)

        if command_name == "declare-fun":
            match = re.match(r"\(declare-fun\s+(\w+)\s+\(([^)]*)\)\s+(\w+)\)\s*$", form)
            if not match:
                raise ValueError(f"Invalid function declaration syntax: {form}")

            domain_str = match.group(2).strip()
            sort_names = [sort_name for sort_name in domain_str.split() if sort_name]
            sort_names.append(match.group(3))
            for sort_name in sort_names:
                self._require_known_sort(sort_name, ctx, command_name)
            return

        if command_name == "declare-const":
            match = re.match(r"\(declare-const\s+(\w+)\s+(\w+)\)\s*$", form)
            if not match:
                raise ValueError(f"Invalid constant declaration syntax: {form}")
            self._require_known_sort(match.group(2), ctx, command_name)
            return

        if command_name == "declare-sort" and not re.match(
            r"\(declare-sort\s+\w+\s+0\)\s*$",
            form,
        ):
            raise ValueError(f"Invalid sort declaration syntax: {form}")

        if command_name == "declare-datatypes" and not re.search(
            r"\(\w+\s+0\)",
            form,
        ):
            raise ValueError(f"Invalid datatype declaration syntax: {form}")

    def _apply_form_to_validation_context(self, form: str, ctx: ConversionContext) -> None:
        """Update a transient validation context after accepting one form."""
        command_name = self._command_name(form)
        if command_name in {"declare-sort", "declare-datatypes"}:
            self._parse_sorts(form, ctx)
        elif command_name == "declare-fun":
            self._parse_functions(form, ctx)
        elif command_name == "declare-const":
            self._parse_constants(form, ctx)

    def _require_known_sort(
        self,
        sort_name: str,
        ctx: ConversionContext,
        stage_name: str,
    ) -> None:
        """Ensure a declaration refers only to known or builtin sorts."""
        if ctx.has_sort(sort_name):
            return
        raise ValueError(
            f"Stage '{stage_name}' referenced unknown sort '{sort_name}'. "
            "Reuse previously declared sorts or declare the sort first."
        )

    def _compose_query_block(
        self,
        *,
        formula: str,
        description: str | None,
        verification_mode: VerificationMode,
    ) -> str:
        """Wrap a boolean formula in a canonical verification block."""
        asserted_formula = formula
        if verification_mode == "entailment":
            asserted_formula = f"(not {formula})"

        lines = []
        if description:
            lines.append(f"; Query: {description}")
        lines.append(f"; Verification mode: {verification_mode}")
        lines.append("(push 1)")
        lines.append(f"(assert {asserted_formula})")
        lines.append("(check-sat)")
        lines.append("(pop 1)")
        return "\n".join(lines)

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

    def _strip_comments(self, output: str) -> str:
        """Remove SMT-LIB comments while preserving other content."""
        return re.sub(r"(?m);[^\n]*$", "", output)

    def _strip_non_stage_commands(self, output: str) -> str:
        """Drop solver-level commands that occasionally leak into stage output."""
        forms_with_comments = self._extract_top_level_forms_with_comments(output)
        if not forms_with_comments:
            return output.strip()
        kept_chunks = []
        for comments, form in forms_with_comments:
            if self._command_name(form) in NON_STAGE_COMMANDS:
                continue
            if comments:
                kept_chunks.append("\n".join(comments))
            kept_chunks.append(form)
        return "\n".join(kept_chunks).strip()

    def _retain_relevant_forms(self, output: str) -> str:
        """Keep only balanced SMT-LIB forms, ignoring stray explanatory text."""
        forms_with_comments = self._extract_top_level_forms_with_comments(output)
        if not forms_with_comments:
            return output.strip()
        chunks = []
        for comments, form in forms_with_comments:
            if comments:
                chunks.append("\n".join(comments))
            chunks.append(form)
        return "\n".join(chunks).strip()

    def _command_name(self, form: str) -> str:
        """Return the top-level command name for a balanced SMT-LIB form."""
        match = re.match(r"\(\s*([^\s()]+)", form)
        if not match:
            raise ValueError(f"Could not determine command name for SMT form: {form}")
        return match.group(1)

    def _extract_top_level_forms(self, output: str) -> list[str]:
        """Extract balanced top-level SMT-LIB forms from raw output."""
        return [form for _comments, form in self._extract_top_level_forms_with_comments(output)]

    def _extract_top_level_forms_with_comments(self, output: str) -> list[tuple[list[str], str]]:
        """Extract balanced top-level SMT-LIB forms and their leading comments."""
        forms: list[tuple[list[str], str]] = []
        pending_comments: list[str] = []
        depth = 0
        start: int | None = None
        form_comments: list[str] = []
        index = 0

        while index < len(output):
            char = output[index]
            if depth == 0 and char == ";":
                newline_index = output.find("\n", index)
                if newline_index == -1:
                    comment = output[index:].rstrip()
                    index = len(output)
                else:
                    comment = output[index:newline_index].rstrip()
                    index = newline_index + 1
                if comment:
                    pending_comments.append(comment)
                continue

            if depth == 0 and char not in {"(", " ", "\t", "\r", "\n"}:
                pending_comments = []

            if char == "(":
                if depth == 0:
                    start = index
                    form_comments = pending_comments
                    pending_comments = []
                depth += 1
            elif char == ")":
                depth -= 1
                if depth < 0:
                    raise ValueError("Unbalanced SMT-LIB parentheses")
                if depth == 0 and start is not None:
                    forms.append((form_comments, output[start : index + 1]))
                    start = None
                    form_comments = []
            index += 1

        if depth != 0:
            raise ValueError("Unbalanced SMT-LIB parentheses")

        return forms

    def _local_zero_arity_symbols(self, output: str, ctx: ConversionContext) -> set[str]:
        """Collect currently known symbols that should never be invoked with empty parens."""
        symbols = set(ctx.constants.keys())
        symbols.update(name for name, func in ctx.functions.items() if not func.domain)
        symbols.update(match.group(1) for match in re.finditer(r"\(declare-const\s+(\w+)\s+\w+\)", output))
        symbols.update(
            match.group(1)
            for match in re.finditer(r"\(declare-fun\s+(\w+)\s+\(\)\s+\w+\)", output)
        )
        return symbols

    def _unwrap_zero_arity_applications(self, output: str, ctx: ConversionContext) -> str:
        """Rewrite `(symbol)` to `symbol` for known constants and zero-arity functions."""
        rewritten = output
        for symbol in sorted(self._local_zero_arity_symbols(output, ctx), key=len, reverse=True):
            rewritten = re.sub(rf"\(\s*{re.escape(symbol)}\s*\)", symbol, rewritten)
        return rewritten

    def _format_stage_repair_prompt(
        self,
        *,
        stage_name: str,
        base_prompt: str,
        stage_input: str,
        failed_output: str,
        error: str,
    ) -> str:
        """Build a focused repair prompt for a single failed stage."""
        stage_rules = {
            "sorts": "Emit only sort declarations. Do not emit set-logic, functions, constants, assertions, or solver commands.",
            "functions": "Emit declarations only. If a symbol has no arguments, declare it with `declare-const`, not `declare-fun`.",
            "constants": "Emit entity declarations only. Do not emit assertions or solver commands.",
            "knowledge_base": "Emit grounded assertions. If you must introduce a missing declaration, declare it first, but do not emit solver commands or duplicate the whole program.",
            "scenario": "Emit scenario-specific declarations and assertions only. Do not restate the whole knowledge base or emit solver commands.",
            "query": "Emit exactly one boolean SMT-LIB formula and nothing else.",
        }
        if self.allow_background_knowledge and stage_name in {"knowledge_base", "scenario"}:
            stage_rules[stage_name] += (
                f" Any assertion that relies on unstated common knowledge must be preceded by "
                f"`{BACKGROUND_KNOWLEDGE_COMMENT}`."
            )
        if self.require_background_knowledge_tags and stage_name in {"knowledge_base", "scenario"}:
            stage_rules[stage_name] += (
                f" Because this run has no external grounding, every assertion in this stage must be "
                f"preceded by `{BACKGROUND_KNOWLEDGE_COMMENT}`."
            )
        return (
            f"{base_prompt}\n\n"
            "## Repair Required\n"
            f"The previous SMT-LIB output for the `{stage_name}` stage is invalid.\n"
            f"Repair ONLY the `{stage_name}` stage output.\n"
            "Do not restate the whole program. Do not add explanations.\n\n"
            f"### Additional repair rule:\n{stage_rules.get(stage_name, 'Emit only SMT-LIB for this stage.')}\n\n"
            "### Stage input:\n"
            f"{stage_input}\n\n"
            "### Current world model summary:\n"
            f"{format_full_context(self.ctx)}\n\n"
            "### Current world model SMT-LIB:\n"
            f"{format_world_model_smt(self.ctx, include_queries=False)}\n\n"
            "### Invalid previous output:\n"
            f"{failed_output or '(empty output)'}\n\n"
            "### Validation or parser error:\n"
            f"{error}\n\n"
            "Output ONLY corrected SMT-LIB for this stage."
        )

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

    def _is_background_knowledge_comment(self, comment: str) -> bool:
        """Return whether a comment marks model-side background knowledge."""
        normalized = comment.lstrip(";").strip().lower().replace("-", "_")
        return normalized.startswith("background_knowledge")

    def _extract_assertion_entries(self, output: str) -> list[tuple[str, bool]]:
        """Extract assertions together with their background-knowledge provenance."""
        entries: list[tuple[str, bool]] = []
        for comments, form in self._extract_top_level_forms_with_comments(output):
            if self._command_name(form) != "assert":
                continue
            uses_background_knowledge = any(
                self._is_background_knowledge_comment(comment) for comment in comments
            )
            entries.append((form, uses_background_knowledge))
        return entries

    def _assertion_smt_code(
        self,
        assertion_code: str,
        *,
        background_knowledge: bool,
    ) -> str:
        """Render assertion code with provenance comments when needed."""
        if not background_knowledge:
            return assertion_code
        return f"{BACKGROUND_KNOWLEDGE_COMMENT}\n{assertion_code}"

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
        self._parse_sorts(output, ctx)
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

        self._parse_constants(output, ctx)

    def _parse_constants(self, output: str, ctx: ConversionContext) -> None:
        """Parse constant declarations from LLM output."""
        self._parse_sorts(output, ctx)
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
        self._parse_sorts(output, ctx)
        self._parse_functions(output, ctx)
        self._parse_constants(output, ctx)
        output = self._apply_aliases(output, ctx)
        for assertion_code, background_knowledge in self._expand_identity_assertions(
            self._extract_assertion_entries(output)
        ):
            assertion_id = f"kb_{len(ctx.kb_assertions)}"
            if any(existing.smt_expr == assertion_code for existing in ctx.kb_assertions.values()):
                continue
            ctx.kb_assertions[assertion_id] = SMTAssertion(
                id=assertion_id,
                dsl_expr="",  # Not from DSL
                smt_expr=assertion_code,
                background_knowledge=background_knowledge,
                smt_code=self._assertion_smt_code(
                    assertion_code,
                    background_knowledge=background_knowledge,
                ),
                emitted=True,
            )

    def _parse_scenario(self, output: str, ctx: ConversionContext) -> None:
        """Parse scenario setup from LLM output."""
        self._parse_sorts(output, ctx)
        self._parse_functions(output, ctx)
        output = self._apply_aliases(output, ctx)
        # Parse any new constants
        self._parse_constants(output, ctx)

        # Parse assertions into scenario_assertions
        existing_assertions = {
            assertion.smt_expr for assertion in ctx.kb_assertions.values() if assertion.smt_expr
        }
        existing_assertions.update(
            assertion.smt_expr
            for assertion in ctx.scenario_assertions.values()
            if assertion.smt_expr
        )
        assertions = self._expand_identity_assertions(self._extract_assertion_entries(output))
        for assertion_code, background_knowledge in assertions:
            if assertion_code in existing_assertions:
                continue
            assertion_id = f"scenario_{len(ctx.scenario_assertions)}"
            ctx.scenario_assertions[assertion_id] = SMTAssertion(
                id=assertion_id,
                dsl_expr="",
                smt_expr=assertion_code,
                background_knowledge=background_knowledge,
                smt_code=self._assertion_smt_code(
                    assertion_code,
                    background_knowledge=background_knowledge,
                ),
                emitted=True,
            )
            existing_assertions.add(assertion_code)

    def _expand_identity_assertions(
        self,
        assertions: list[tuple[str, bool]],
    ) -> list[tuple[str, bool]]:
        """Add equality assertions for explicit identity relations.

        This exists because the LLM often models "X is the same entity as Y" as
        an uninterpreted predicate. Without an explicit `=` assertion, queries
        over one alias do not inherit facts asserted over the other.
        """
        expanded: list[tuple[str, bool]] = []
        seen: set[str] = set()
        for assertion_code, background_knowledge in assertions:
            for candidate in (
                assertion_code,
                self._derive_identity_equality(assertion_code),
            ):
                if not candidate or candidate in seen:
                    continue
                expanded.append((candidate, background_knowledge))
                seen.add(candidate)
        return expanded

    def _derive_identity_equality(self, assertion_code: str) -> str | None:
        """Convert direct identity-relation assertions into built-in equality."""
        match = re.fullmatch(
            r"\(assert\s+\((\w+)\s+([^\s()]+)\s+([^\s()]+)\)\s*\)",
            assertion_code.strip(),
        )
        if not match:
            return None

        relation_name, lhs, rhs = match.groups()
        if relation_name not in IDENTITY_RELATION_NAMES or lhs == rhs:
            return None
        return f"(assert (= {lhs} {rhs}))"

    def _parse_query(self, output: str, ctx: ConversionContext) -> None:
        """Parse query from LLM output."""
        output = self._apply_aliases(output, ctx)
        formula, description = self._normalize_query_formula(output)
        smt_code = self._compose_query_block(
            formula=formula,
            description=description or "verification",
            verification_mode=self.verification_mode,
        )
        query_id = f"query_{len(ctx.queries)}"
        ctx.queries[query_id] = SMTQuery(
            id=query_id,
            name=description or "verification",
            formula=formula,
            verification_mode=self.verification_mode,
            assertions=[],
            check_model=False,
            smt_code=smt_code,
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
        del stage_outputs
        return self.compose_context_program(
            include_scenario=True,
            include_queries=True,
        )

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
        return format_world_model_smt(
            self.ctx,
            include_scenario=include_scenario,
            include_queries=include_queries,
        )


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
