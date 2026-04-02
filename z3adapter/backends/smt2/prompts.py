"""Stage-specific prompt templates for LLM-driven SMT-LIB generation.

The prompt layer carries a few deliberate constraints that are easy to forget
later when looking only at the runtime:

- every stage receives the full accumulated world model, not just a symbol list
- the query stage emits only a boolean formula; the runtime wraps it in the
  canonical push/assert/check-sat/pop block
- stage prompts are intentionally narrow because benchmark failures were often
  caused by the model drifting into whole-program generation
- background-knowledge mode is explicit and auditable: if the model relies on
  unstated common knowledge, it must mark those assertions with a comment so the
  resulting proof artifact can be treated as lower-rigor than strict grounding
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from z3adapter.backends.smt2.ir import ConversionContext


# Base instructions for all stages. The "world model is authoritative" line is
# important: stage quality degraded when the model saw only summaries and had to
# reconstruct prior declarations from memory. Background-knowledge mode is
# opt-in so strict grounded verification remains the default product behavior.
BACKGROUND_KNOWLEDGE_COMMENT = "; background_knowledge"


BASE_INSTRUCTIONS = """You are generating SMT-LIB 2.0 code for formal verification.

SMT-LIB uses S-expressions (parenthesized prefix notation):
- Commands: (command arg1 arg2 ...)
- Comments start with ;

Output ONLY valid SMT-LIB code. No explanations, no markdown.

Do not invent facts that are not grounded in the provided text or scenario.
Use only symbols that are already declared or clearly required by the input.
The accumulated world model below is authoritative. Reuse and extend it consistently."""


BACKGROUND_KNOWLEDGE_INSTRUCTIONS = f"""You may also use widely known background knowledge when strict grounding is unavailable or insufficient.

If you rely on background knowledge that is not explicitly stated in the provided text or scenario:
- emit the assertion normally
- place the exact comment `{BACKGROUND_KNOWLEDGE_COMMENT}` immediately above that assertion
- use this sparingly and only for stable, widely known facts

Tagged background-knowledge assertions are treated as lower-rigor than strictly grounded assertions."""


# Stage 1: Sorts
SORTS_PROMPT = """{base}

## Current Task: Define Sorts (Types)

Analyze the text and identify all distinct entity types, categories, or domains.

### SMT-LIB Sort Syntax:
- Uninterpreted sort: (declare-sort SortName 0)
- Enumeration: (declare-datatypes ((EnumName 0)) (((val1) (val2) (val3))))

### Guidelines:
- Use PascalCase for sort names (Person, Ticket, Request)
- Prefer a small number of reusable sorts
- Default to a single `Entity`-style sort unless there is a clear need for incompatible domains
- Model categories and properties as predicates, not as separate sorts
- Use enumerations for finite sets of values (days of week, status codes)
- Built-in sorts available: Bool, Int, Real, String

### Text to analyze:
{text}

### Current world model summary:
{context_summary}

### Current world model SMT-LIB:
{world_model_smt}

Output the (declare-sort ...) and (declare-datatypes ...) commands:"""


# Stage 2: Functions
FUNCTIONS_PROMPT = """{base}

## Current Task: Define Functions and Predicates

Analyze the text and identify properties, relationships, and computations.

### SMT-LIB Function Syntax:
- (declare-fun name (ArgSort1 ArgSort2) ReturnSort)
- Predicates return Bool: (declare-fun is_valid (Ticket) Bool)
- Functions return other sorts: (declare-fun price (Ticket) Int)

### Guidelines:
- Use snake_case for function names
- Predicates (returning Bool): is_X, has_X, can_X for properties
- Relations: relates_to(A, B) for relationships between entities
- Attributes: attribute_name(Entity) for entity properties
- If a symbol has no arguments, declare it with `(declare-const ...)`, not `(declare-fun ...)`
- Time values use Int (seconds/timestamps)
- Prefer unary predicates for categories like `is_student`, `is_wumpus`, `is_blue`
- Do not create new symbols whose only purpose is to restate the question in prose

### Text to analyze:
{text}

### Available sorts:
{sorts}

### Already defined functions (do not redefine):
{existing_functions}

### Current world model summary:
{context_summary}

### Current world model SMT-LIB:
{world_model_smt}

Output the (declare-fun ...) commands:"""


# Stage 3: Constants
CONSTANTS_PROMPT = """{base}

## Current Task: Declare Constants (Specific Entities)

Identify specific named entities, instances, or values mentioned in the text.

### SMT-LIB Constant Syntax:
- (declare-const name Sort)

### Guidelines:
- Use snake_case for constant names
- Declare constants for specific entities mentioned by name
- For scenario variables (like "the ticket" or "a request"), use descriptive names like t0, r0
- Do not declare constants for classes, categories, or predicates

### Text to analyze:
{text}

### Available sorts:
{sorts}

### Already declared constants (do not redeclare):
{existing_constants}

### Current world model summary:
{context_summary}

### Current world model SMT-LIB:
{world_model_smt}

Output the (declare-const ...) commands:"""


# Stage 4: Knowledge Base (Policy/Rules)
KNOWLEDGE_BASE_PROMPT = """{base}

## Current Task: Encode Knowledge Base (Facts and Rules)

Translate the rules, constraints, and facts from the text into logical assertions.

### SMT-LIB Assertion Syntax:
- Simple fact: (assert (predicate constant))
- Negation: (assert (not (predicate constant)))
- Implication: (assert (=> antecedent consequent))
- Universal: (assert (forall ((x Sort)) body))
- Conjunction: (and expr1 expr2 ...)
- Disjunction: (or expr1 expr2 ...)
- Arithmetic: (+ a b), (- a b), (* a b), (<= a b), (>= a b)

### Guidelines:
- Encode general rules with (forall ...)
- Encode specific facts directly
- If a needed symbol is missing, declare it before asserting over it
- Time constraints: use arithmetic on Int timestamps
- "must" / "required" → implications or assertions
- "within X hours" → (<= (- time2 time1) (* X 3600))
- If you use background knowledge that is not explicitly stated in the text, tag each such assertion with `{background_knowledge_comment}` on the line immediately above it

### Text to analyze:
{text}

### Available sorts:
{sorts}

### Available functions:
{functions}

### Available constants:
{constants}

### Existing assertions (context):
{existing_kb}

### Current world model summary:
{context_summary}

### Current world model SMT-LIB:
{world_model_smt}

Output the (assert ...) commands for the knowledge base:"""


# Stage 5: Scenario Setup
SCENARIO_PROMPT = """{base}

## Current Task: Encode the Specific Scenario

Set up the specific scenario from the question for verification.

### Guidelines:
- Declare scenario-specific constants if needed
- Assert only scenario-specific facts that are newly introduced by the question
- Set up the state before the query
- Do not restate or duplicate knowledge-base assertions
- Do not use background knowledge here unless the question itself introduces it as scenario context
- If the question adds no scenario facts, output nothing

### Question/Scenario:
{question}

### Available sorts:
{sorts}

### Available functions:
{functions}

### Available constants:
{constants}

### Knowledge base (already asserted):
{kb_summary}

### Current world model summary:
{context_summary}

### Current world model SMT-LIB:
{world_model_smt}

Output the scenario setup (declare-const and assert commands):"""


# Stage 6: Query. The model emits only the claim formula so the runtime can own
# verification semantics and avoid ambiguity around direct assertion vs
# counterexample-style wrapping.
QUERY_PROMPT = """{base}

## Current Task: Formulate the Verification Claim

Create ONLY the final boolean SMT-LIB formula to verify.

### Verification Semantics:
- Mode: {verification_mode}
- In `entailment` mode, output the positive claim whose truth should follow from the knowledge base and scenario
- Do NOT negate the claim in entailment mode
- In `consistency` mode, output the condition whose consistency should be checked directly

### Output Rules:
- Output only one SMT-LIB boolean expression
- Do NOT output `(assert ...)`, `(check-sat)`, `(get-model)`, `(push ...)`, or `(pop ...)`
- Do NOT introduce new constants, functions, or unsupported facts
- Reuse only the declared symbols listed below

### Question to verify:
{question}

### Available sorts:
{sorts}

### Available functions:
{functions}

### Available constants (including scenario):
{constants}

### What has been asserted:
{assertions_summary}

### Current world model summary:
{context_summary}

### Current world model SMT-LIB:
{world_model_smt}

Output the query block:"""


def format_base_instructions(*, allow_background_knowledge: bool) -> str:
    """Build the base instruction block for the current grounding policy."""
    sections = [BASE_INSTRUCTIONS]
    if allow_background_knowledge:
        sections.append(BACKGROUND_KNOWLEDGE_INSTRUCTIONS)
    return "\n\n".join(sections)


def format_sorts_prompt(
    text: str,
    ctx: ConversionContext,
    *,
    allow_background_knowledge: bool = False,
) -> str:
    """Format the sorts stage prompt."""
    return SORTS_PROMPT.format(
        base=format_base_instructions(allow_background_knowledge=allow_background_knowledge),
        text=text,
        context_summary=format_full_context(ctx),
        world_model_smt=format_world_model_smt(ctx, include_queries=False),
    )


def format_functions_prompt(
    text: str,
    ctx: ConversionContext,
    *,
    allow_background_knowledge: bool = False,
) -> str:
    """Format the functions stage prompt."""
    sorts = ", ".join(ctx.sorts.keys()) if ctx.sorts else "(none)"
    existing = ", ".join(ctx.functions.keys()) if ctx.functions else "(none)"

    return FUNCTIONS_PROMPT.format(
        base=format_base_instructions(allow_background_knowledge=allow_background_knowledge),
        text=text,
        sorts=sorts,
        existing_functions=existing,
        context_summary=format_full_context(ctx),
        world_model_smt=format_world_model_smt(ctx, include_queries=False),
    )


def format_constants_prompt(
    text: str,
    ctx: ConversionContext,
    *,
    allow_background_knowledge: bool = False,
) -> str:
    """Format the constants stage prompt."""
    sorts = ", ".join(ctx.sorts.keys()) if ctx.sorts else "(none)"
    existing = ", ".join(ctx.constants.keys()) if ctx.constants else "(none)"

    return CONSTANTS_PROMPT.format(
        base=format_base_instructions(allow_background_knowledge=allow_background_knowledge),
        text=text,
        sorts=sorts,
        existing_constants=existing,
        context_summary=format_full_context(ctx),
        world_model_smt=format_world_model_smt(ctx, include_queries=False),
    )


def format_kb_prompt(
    text: str,
    ctx: ConversionContext,
    *,
    allow_background_knowledge: bool = False,
) -> str:
    """Format the knowledge base stage prompt."""
    sorts = ", ".join(ctx.sorts.keys()) if ctx.sorts else "(none)"
    functions = (
        ", ".join(
            f"{name}({','.join(f.domain)})->{f.range_sort}" for name, f in ctx.functions.items()
        )
        if ctx.functions
        else "(none)"
    )
    constants = (
        ", ".join(f"{name}:{c.sort}" for name, c in ctx.constants.items())
        if ctx.constants
        else "(none)"
    )
    existing_kb = (
        "\n".join(a.smt_code for a in ctx.kb_assertions.values()) if ctx.kb_assertions else "(none)"
    )

    return KNOWLEDGE_BASE_PROMPT.format(
        base=format_base_instructions(allow_background_knowledge=allow_background_knowledge),
        text=text,
        sorts=sorts,
        functions=functions,
        constants=constants,
        existing_kb=existing_kb,
        background_knowledge_comment=BACKGROUND_KNOWLEDGE_COMMENT,
        context_summary=format_full_context(ctx),
        world_model_smt=format_world_model_smt(ctx, include_queries=False),
    )


def format_scenario_prompt(
    question: str,
    ctx: ConversionContext,
    *,
    allow_background_knowledge: bool = False,
) -> str:
    """Format the scenario stage prompt."""
    sorts = ", ".join(ctx.sorts.keys()) if ctx.sorts else "(none)"
    functions = ", ".join(ctx.functions.keys()) if ctx.functions else "(none)"
    constants = ", ".join(ctx.constants.keys()) if ctx.constants else "(none)"
    kb_summary = f"{len(ctx.kb_assertions)} assertions" if ctx.kb_assertions else "(none)"

    return SCENARIO_PROMPT.format(
        base=format_base_instructions(allow_background_knowledge=allow_background_knowledge),
        question=question,
        sorts=sorts,
        functions=functions,
        constants=constants,
        kb_summary=kb_summary,
        context_summary=format_full_context(ctx),
        world_model_smt=format_world_model_smt(ctx, include_queries=False),
    )


def format_query_prompt(
    question: str,
    ctx: ConversionContext,
    verification_mode: str,
    *,
    allow_background_knowledge: bool = False,
) -> str:
    """Format the query stage prompt."""
    sorts = ", ".join(ctx.sorts.keys()) if ctx.sorts else "(none)"
    functions = ", ".join(ctx.functions.keys()) if ctx.functions else "(none)"
    constants = ", ".join(ctx.constants.keys()) if ctx.constants else "(none)"

    total_assertions = len(ctx.kb_assertions) + len(ctx.scenario_assertions)
    assertions_summary = f"{total_assertions} total assertions"

    return QUERY_PROMPT.format(
        base=format_base_instructions(allow_background_knowledge=allow_background_knowledge),
        question=question,
        sorts=sorts,
        functions=functions,
        constants=constants,
        assertions_summary=assertions_summary,
        verification_mode=verification_mode,
        context_summary=format_full_context(ctx),
        world_model_smt=format_world_model_smt(ctx, include_queries=False),
    )


def format_full_context(ctx: ConversionContext) -> str:
    """Format a full context summary for the LLM."""
    lines = [
        "; === Current SMT-LIB Context ===",
        f"; Logic: {ctx.logic}",
        "",
    ]

    if ctx.sorts:
        lines.append("; Sorts:")
        for name, sort in ctx.sorts.items():
            lines.append(f";   {name} ({sort.kind.value})")
        lines.append("")

    if ctx.functions:
        lines.append("; Functions:")
        for name, func in ctx.functions.items():
            domain = ", ".join(func.domain) if func.domain else ""
            lines.append(f";   {name}({domain}) -> {func.range_sort}")
        lines.append("")

    if ctx.constants:
        lines.append("; Constants:")
        for name, const in ctx.constants.items():
            lines.append(f";   {name}: {const.sort}")
        lines.append("")

    if ctx.kb_assertions:
        lines.append(f"; Knowledge Base: {len(ctx.kb_assertions)} assertions")
        lines.append("")

    if ctx.queries:
        lines.append(f"; Queries: {len(ctx.queries)}")
        lines.append("")

    return "\n".join(lines)


def format_world_model_smt(
    ctx: ConversionContext,
    *,
    include_scenario: bool = True,
    include_queries: bool = False,
) -> str:
    """Render canonical SMT-LIB for the currently accumulated world model."""
    parts = [f"(set-logic {ctx.logic})", ""]

    section_defs: list[tuple[str, list[str]]] = [
        (
            "Sorts",
            [sort.smt_code for sort in ctx.sorts.values() if sort.smt_code],
        ),
        (
            "Functions",
            [func.smt_code for func in ctx.functions.values() if func.smt_code],
        ),
        (
            "Constants",
            [const.smt_code for const in ctx.constants.values() if const.smt_code],
        ),
        (
            "Knowledge Base",
            [
                assertion.smt_code
                for assertion in ctx.kb_assertions.values()
                if assertion.smt_code
            ],
        ),
        (
            "Rules",
            [rule.smt_code for rule in ctx.rules.values() if rule.smt_code],
        ),
    ]

    if include_scenario:
        section_defs.append(
            (
                "Scenario",
                [
                    assertion.smt_code
                    for assertion in ctx.scenario_assertions.values()
                    if assertion.smt_code
                ],
            )
        )

    if include_queries:
        section_defs.append(
            (
                "Queries",
                [query.smt_code for query in ctx.queries.values() if query.smt_code],
            )
        )

    added_sections = 0
    for section_name, lines in section_defs:
        if not lines:
            continue
        parts.append(f"; --- {section_name} ---")
        parts.extend(lines)
        parts.append("")
        added_sections += 1

    if added_sections == 0:
        return f"(set-logic {ctx.logic})\n; No declarations or assertions have been emitted yet."

    return "\n".join(parts).rstrip()
