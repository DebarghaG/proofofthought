"""Intermediate Representation for SMT-LIB conversion tracking."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SMTSortKind(Enum):
    """Kind of SMT-LIB sort."""

    BUILTIN = "builtin"  # Bool, Int, Real
    UNINTERPRETED = "uninterpreted"  # (declare-sort X 0)
    ENUM = "enum"  # (declare-datatypes ...)
    BITVEC = "bitvec"  # (_ BitVec n)
    ARRAY = "array"  # (Array K V)


@dataclass
class SMTSort:
    """Represents an SMT-LIB sort."""

    name: str  # DSL name (e.g., "Person")
    kind: SMTSortKind
    smt_name: str  # SMT-LIB name (usually same as name)
    params: dict[str, Any] = field(default_factory=dict)
    # For enum: {"values": ["red", "green", "blue"]}
    # For bitvec: {"size": 32}
    # For array: {"domain": "Int", "range": "Bool"}

    emitted: bool = False  # Has SMT-LIB been emitted?
    smt_code: str = ""  # Generated SMT-LIB code


@dataclass
class SMTFunction:
    """Represents an SMT-LIB function declaration."""

    name: str  # DSL function name
    smt_name: str  # SMT-LIB function name
    domain: list[str] = field(default_factory=list)  # List of sort names
    range_sort: str = ""  # Return sort name

    emitted: bool = False
    smt_code: str = ""


@dataclass
class SMTConstant:
    """Represents an SMT-LIB constant."""

    name: str  # DSL constant name
    smt_name: str  # SMT-LIB constant name
    sort: str  # Sort name

    emitted: bool = False
    smt_code: str = ""


@dataclass
class SMTAssertion:
    """Represents an SMT-LIB assertion."""

    id: str  # Unique identifier
    dsl_expr: str  # Original DSL expression
    smt_expr: str  # SMT-LIB expression
    label: str | None = None  # Optional label for named assertions

    emitted: bool = False
    smt_code: str = ""


@dataclass
class SMTQuery:
    """Represents a query (check-sat + optional get-model/get-value)."""

    id: str  # Unique query identifier
    name: str  # Human-readable name
    assertions: list[str] = field(default_factory=list)  # Additional assertion IDs
    check_model: bool = True  # Whether to emit (get-model)
    get_values: list[str] = field(default_factory=list)  # Expressions for (get-value)

    emitted: bool = False
    smt_code: str = ""


@dataclass
class ConversionContext:
    """
    Tracks all converted elements and their SMT-LIB mappings.

    This is the "conversion ledger" that enables:
    - Incremental generation
    - Consistency across chunks
    - LLM context preservation
    """

    logic: str = "ALL"  # SMT-LIB logic (default: ALL for maximum flexibility)

    # Converted sorts (name -> SMTSort)
    sorts: dict[str, SMTSort] = field(default_factory=dict)

    # Converted functions (name -> SMTFunction)
    functions: dict[str, SMTFunction] = field(default_factory=dict)

    # Converted constants (name -> SMTConstant)
    constants: dict[str, SMTConstant] = field(default_factory=dict)

    # Free variables (name -> sort_name) - for quantifier-bound variables
    variables: dict[str, str] = field(default_factory=dict)

    # Knowledge base assertions (id -> SMTAssertion)
    kb_assertions: dict[str, SMTAssertion] = field(default_factory=dict)

    # Rules — universally quantified assertions (id -> SMTAssertion)
    rules: dict[str, SMTAssertion] = field(default_factory=dict)

    # Scenario assertions (for queries) (id -> SMTAssertion)
    scenario_assertions: dict[str, SMTAssertion] = field(default_factory=dict)

    # Queries (id -> SMTQuery)
    queries: dict[str, SMTQuery] = field(default_factory=dict)

    # Emission order tracking
    emission_order: list[str] = field(default_factory=list)  # IDs in emission order

    # Symbol aliases used to normalize LLM-generated names to canonical SMT names.
    symbol_aliases: dict[str, str] = field(default_factory=dict)

    def has_sort(self, name: str) -> bool:
        """Check if sort has been registered or is a built-in."""
        builtin_sorts = {"Bool", "Int", "Real", "BoolSort", "IntSort", "RealSort"}
        return name in self.sorts or name in builtin_sorts

    def resolve_sort_name(self, name: str) -> str:
        """Resolve a DSL sort name to its SMT-LIB name."""
        # Handle built-in sort aliases
        builtin_map = {
            "BoolSort": "Bool",
            "IntSort": "Int",
            "RealSort": "Real",
        }
        if name in builtin_map:
            return builtin_map[name]
        if name in ("Bool", "Int", "Real"):
            return name
        # Look up user-defined sort
        if name in self.sorts:
            return self.sorts[name].smt_name
        logger.warning(
            f"Sort '{name}' not found in context (not a builtin and not declared). "
            f"Passing through as-is. Declared sorts: {list(self.sorts.keys())}"
        )
        return name

    def get_unemitted(self) -> list[str]:
        """Get IDs of unemitted elements."""
        unemitted = []
        for name, sort in self.sorts.items():
            if not sort.emitted:
                unemitted.append(f"sort:{name}")
        for name, func in self.functions.items():
            if not func.emitted:
                unemitted.append(f"func:{name}")
        for name, const in self.constants.items():
            if not const.emitted:
                unemitted.append(f"const:{name}")
        for id_, assertion in self.kb_assertions.items():
            if not assertion.emitted:
                unemitted.append(f"kb:{id_}")
        for id_, assertion in self.rules.items():
            if not assertion.emitted:
                unemitted.append(f"rule:{id_}")
        for id_, assertion in self.scenario_assertions.items():
            if not assertion.emitted:
                unemitted.append(f"scenario:{id_}")
        for id_, query in self.queries.items():
            if not query.emitted:
                unemitted.append(f"query:{id_}")
        return unemitted

    def to_summary(self) -> str:
        """Generate a summary string for LLM context."""
        lines = [f"; Logic: {self.logic}"]
        if self.sorts:
            sort_names = [s for s in self.sorts.keys() if self.sorts[s].kind != SMTSortKind.BUILTIN]
            if sort_names:
                lines.append(f"; Sorts: {', '.join(sort_names)}")
        if self.functions:
            lines.append(f"; Functions: {', '.join(self.functions.keys())}")
        if self.constants:
            lines.append(f"; Constants: {', '.join(self.constants.keys())}")
        if self.variables:
            lines.append(f"; Variables: {', '.join(self.variables.keys())}")
        lines.append(f"; KB assertions: {len(self.kb_assertions)}")
        lines.append(f"; Rules: {len(self.rules)}")
        lines.append(f"; Queries: {len(self.queries)}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert context to a dictionary for serialization."""
        return {
            "logic": self.logic,
            "sorts": {
                name: {
                    "name": sort.name,
                    "kind": sort.kind.value,
                    "smt_name": sort.smt_name,
                    "params": sort.params,
                    "emitted": sort.emitted,
                    "smt_code": sort.smt_code,
                }
                for name, sort in self.sorts.items()
            },
            "functions": {
                name: {
                    "name": func.name,
                    "smt_name": func.smt_name,
                    "domain": func.domain,
                    "range_sort": func.range_sort,
                    "emitted": func.emitted,
                    "smt_code": func.smt_code,
                }
                for name, func in self.functions.items()
            },
            "constants": {
                name: {
                    "name": const.name,
                    "smt_name": const.smt_name,
                    "sort": const.sort,
                    "emitted": const.emitted,
                    "smt_code": const.smt_code,
                }
                for name, const in self.constants.items()
            },
            "variables": self.variables,
            "symbol_aliases": self.symbol_aliases,
            "kb_assertions": {
                name: {
                    "id": assertion.id,
                    "dsl_expr": assertion.dsl_expr,
                    "smt_expr": assertion.smt_expr,
                    "label": assertion.label,
                    "emitted": assertion.emitted,
                    "smt_code": assertion.smt_code,
                }
                for name, assertion in self.kb_assertions.items()
            },
            "rules": {
                name: {
                    "id": assertion.id,
                    "dsl_expr": assertion.dsl_expr,
                    "smt_expr": assertion.smt_expr,
                    "label": assertion.label,
                    "emitted": assertion.emitted,
                    "smt_code": assertion.smt_code,
                }
                for name, assertion in self.rules.items()
            },
            "scenario_assertions": {
                name: {
                    "id": assertion.id,
                    "dsl_expr": assertion.dsl_expr,
                    "smt_expr": assertion.smt_expr,
                    "label": assertion.label,
                    "emitted": assertion.emitted,
                    "smt_code": assertion.smt_code,
                }
                for name, assertion in self.scenario_assertions.items()
            },
            "queries": {
                name: {
                    "id": query.id,
                    "name": query.name,
                    "assertions": query.assertions,
                    "check_model": query.check_model,
                    "get_values": query.get_values,
                    "emitted": query.emitted,
                    "smt_code": query.smt_code,
                }
                for name, query in self.queries.items()
            },
            "emission_order": self.emission_order,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversionContext":
        """Rebuild a conversion context from serialized data."""
        ctx = cls(logic=data.get("logic", "ALL"))

        for name, sort in data.get("sorts", {}).items():
            ctx.sorts[name] = SMTSort(
                name=sort.get("name", name),
                kind=SMTSortKind(sort["kind"]),
                smt_name=sort.get("smt_name", name),
                params=dict(sort.get("params", {})),
                emitted=bool(sort.get("emitted", False)),
                smt_code=sort.get("smt_code", ""),
            )

        for name, func in data.get("functions", {}).items():
            ctx.functions[name] = SMTFunction(
                name=func.get("name", name),
                smt_name=func.get("smt_name", name),
                domain=list(func.get("domain", [])),
                range_sort=func.get("range_sort", ""),
                emitted=bool(func.get("emitted", False)),
                smt_code=func.get("smt_code", ""),
            )

        for name, const in data.get("constants", {}).items():
            ctx.constants[name] = SMTConstant(
                name=const.get("name", name),
                smt_name=const.get("smt_name", name),
                sort=const.get("sort", ""),
                emitted=bool(const.get("emitted", False)),
                smt_code=const.get("smt_code", ""),
            )

        ctx.variables = dict(data.get("variables", {}))
        ctx.symbol_aliases = dict(data.get("symbol_aliases", {}))

        for name, assertion in data.get("kb_assertions", {}).items():
            ctx.kb_assertions[name] = SMTAssertion(
                id=assertion.get("id", name),
                dsl_expr=assertion.get("dsl_expr", ""),
                smt_expr=assertion.get("smt_expr", ""),
                label=assertion.get("label"),
                emitted=bool(assertion.get("emitted", False)),
                smt_code=assertion.get("smt_code", ""),
            )

        for name, assertion in data.get("rules", {}).items():
            ctx.rules[name] = SMTAssertion(
                id=assertion.get("id", name),
                dsl_expr=assertion.get("dsl_expr", ""),
                smt_expr=assertion.get("smt_expr", ""),
                label=assertion.get("label"),
                emitted=bool(assertion.get("emitted", False)),
                smt_code=assertion.get("smt_code", ""),
            )

        for name, assertion in data.get("scenario_assertions", {}).items():
            ctx.scenario_assertions[name] = SMTAssertion(
                id=assertion.get("id", name),
                dsl_expr=assertion.get("dsl_expr", ""),
                smt_expr=assertion.get("smt_expr", ""),
                label=assertion.get("label"),
                emitted=bool(assertion.get("emitted", False)),
                smt_code=assertion.get("smt_code", ""),
            )

        for name, query in data.get("queries", {}).items():
            ctx.queries[name] = SMTQuery(
                id=query.get("id", name),
                name=query.get("name", name),
                assertions=list(query.get("assertions", [])),
                check_model=bool(query.get("check_model", True)),
                get_values=list(query.get("get_values", [])),
                emitted=bool(query.get("emitted", False)),
                smt_code=query.get("smt_code", ""),
            )

        ctx.emission_order = list(data.get("emission_order", []))
        return ctx
