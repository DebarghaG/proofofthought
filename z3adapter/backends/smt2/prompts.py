"""Stage-specific prompt templates for LLM-driven SMT-LIB generation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from z3adapter.backends.smt2.ir import ConversionContext


# Base instructions for all stages
BASE_INSTRUCTIONS = """You are generating SMT-LIB 2.0 code for formal verification.

SMT-LIB uses S-expressions (parenthesized prefix notation):
- Commands: (command arg1 arg2 ...)
- Comments start with ;

Output ONLY valid SMT-LIB code. No explanations, no markdown."""


# Stage 1: Sorts
SORTS_PROMPT = """{base}

## Current Task: Define Sorts (Types)

Analyze the text and identify all distinct entity types, categories, or domains.

### SMT-LIB Sort Syntax:
- Uninterpreted sort: (declare-sort SortName 0)
- Enumeration: (declare-datatypes ((EnumName 0)) (((val1) (val2) (val3))))

### Guidelines:
- Use PascalCase for sort names (Person, Ticket, Request)
- Create a sort for each distinct category of entities
- Use enumerations for finite sets of values (days of week, status codes)
- Built-in sorts available: Bool, Int, Real, String

### Text to analyze:
{text}

### Already defined (do not redefine):
{context}

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
- Time values use Int (seconds/timestamps)

### Text to analyze:
{text}

### Available sorts:
{sorts}

### Already defined functions (do not redefine):
{existing_functions}

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

### Text to analyze:
{text}

### Available sorts:
{sorts}

### Already declared constants (do not redeclare):
{existing_constants}

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
- Time constraints: use arithmetic on Int timestamps
- "must" / "required" → implications or assertions
- "within X hours" → (<= (- time2 time1) (* X 3600))

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

Output the (assert ...) commands for the knowledge base:"""


# Stage 5: Scenario Setup
SCENARIO_PROMPT = """{base}

## Current Task: Encode the Specific Scenario

Set up the specific scenario from the question for verification.

### Guidelines:
- Declare scenario-specific constants if needed
- Assert the conditions described in the scenario
- Set up the state before the query

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

Output the scenario setup (declare-const and assert commands):"""


# Stage 6: Query
QUERY_PROMPT = """{base}

## Current Task: Formulate the Verification Query

Create the final assertion to check and the (check-sat) command.

### Verification Semantics:
- sat = the scenario is POSSIBLE/CONSISTENT with the rules
- unsat = the scenario is IMPOSSIBLE/CONTRADICTS the rules

### Query Pattern:
; Query: <description>
(push 1)
(assert <condition_to_check>)
(check-sat)
(get-model)
(pop 1)

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

Output the query block:"""


def format_sorts_prompt(text: str, ctx: ConversionContext) -> str:
    """Format the sorts stage prompt."""
    context = ""
    if ctx.sorts:
        context = "; ".join(f"{name}: {s.kind.value}" for name, s in ctx.sorts.items())
    else:
        context = "(none)"

    return SORTS_PROMPT.format(
        base=BASE_INSTRUCTIONS,
        text=text,
        context=context,
    )


def format_functions_prompt(text: str, ctx: ConversionContext) -> str:
    """Format the functions stage prompt."""
    sorts = ", ".join(ctx.sorts.keys()) if ctx.sorts else "(none)"
    existing = ", ".join(ctx.functions.keys()) if ctx.functions else "(none)"

    return FUNCTIONS_PROMPT.format(
        base=BASE_INSTRUCTIONS,
        text=text,
        sorts=sorts,
        existing_functions=existing,
    )


def format_constants_prompt(text: str, ctx: ConversionContext) -> str:
    """Format the constants stage prompt."""
    sorts = ", ".join(ctx.sorts.keys()) if ctx.sorts else "(none)"
    existing = ", ".join(ctx.constants.keys()) if ctx.constants else "(none)"

    return CONSTANTS_PROMPT.format(
        base=BASE_INSTRUCTIONS,
        text=text,
        sorts=sorts,
        existing_constants=existing,
    )


def format_kb_prompt(text: str, ctx: ConversionContext) -> str:
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
        base=BASE_INSTRUCTIONS,
        text=text,
        sorts=sorts,
        functions=functions,
        constants=constants,
        existing_kb=existing_kb,
    )


def format_scenario_prompt(question: str, ctx: ConversionContext) -> str:
    """Format the scenario stage prompt."""
    sorts = ", ".join(ctx.sorts.keys()) if ctx.sorts else "(none)"
    functions = ", ".join(ctx.functions.keys()) if ctx.functions else "(none)"
    constants = ", ".join(ctx.constants.keys()) if ctx.constants else "(none)"
    kb_summary = f"{len(ctx.kb_assertions)} assertions" if ctx.kb_assertions else "(none)"

    return SCENARIO_PROMPT.format(
        base=BASE_INSTRUCTIONS,
        question=question,
        sorts=sorts,
        functions=functions,
        constants=constants,
        kb_summary=kb_summary,
    )


def format_query_prompt(question: str, ctx: ConversionContext) -> str:
    """Format the query stage prompt."""
    sorts = ", ".join(ctx.sorts.keys()) if ctx.sorts else "(none)"
    functions = ", ".join(ctx.functions.keys()) if ctx.functions else "(none)"
    constants = ", ".join(ctx.constants.keys()) if ctx.constants else "(none)"

    total_assertions = len(ctx.kb_assertions) + len(ctx.scenario_assertions)
    assertions_summary = f"{total_assertions} total assertions"

    return QUERY_PROMPT.format(
        base=BASE_INSTRUCTIONS,
        question=question,
        sorts=sorts,
        functions=functions,
        constants=constants,
        assertions_summary=assertions_summary,
    )


# Full context prompt for LLM to understand what's been generated
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
