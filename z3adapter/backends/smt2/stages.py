"""Pipeline stages for SMT-LIB generation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from z3adapter.backends.smt2.ir import (
    ConversionContext,
    SMTAssertion,
    SMTConstant,
    SMTFunction,
    SMTQuery,
    SMTSort,
    SMTSortKind,
)


class PipelineStage(ABC):
    """Abstract base class for pipeline stages."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stage name for logging and identification."""
        pass

    @abstractmethod
    def process(self, ctx: ConversionContext, config: dict[str, Any]) -> str:
        """
        Process this stage, updating context and returning SMT-LIB code.

        Args:
            ctx: Conversion context to update
            config: Stage-specific configuration

        Returns:
            SMT-LIB code for this stage
        """
        pass


class LogicStage(PipelineStage):
    """Stage 1: Emit (set-logic ...) command."""

    @property
    def name(self) -> str:
        return "logic"

    def process(self, ctx: ConversionContext, config: dict[str, Any]) -> str:
        logic = config.get("logic", "ALL")
        ctx.logic = logic
        return f"(set-logic {logic})\n"


class SortsStage(PipelineStage):
    """Stage 2: Process and emit sort declarations."""

    @property
    def name(self) -> str:
        return "sorts"

    def process(self, ctx: ConversionContext, config: dict[str, Any]) -> str:
        sort_defs = config.get("sorts", [])
        if not sort_defs:
            return ""

        lines = ["; --- Sorts ---"]

        # Topological sort to handle dependencies
        sorted_defs = self._topological_sort(sort_defs, ctx)

        for sort_def in sorted_defs:
            smt_sort = self._create_sort(sort_def, ctx)
            ctx.sorts[smt_sort.name] = smt_sort
            if smt_sort.smt_code:
                lines.append(smt_sort.smt_code)
                smt_sort.emitted = True

        return "\n".join(lines) + "\n" if len(lines) > 1 else ""

    def _topological_sort(self, sort_defs: list[dict], ctx: ConversionContext) -> list[dict]:
        """Sort definitions by dependencies (similar to SortManager)."""
        if not sort_defs:
            return []

        # Build dependency graph
        dependencies: dict[str, list[str]] = {}
        for sd in sort_defs:
            name = sd.get("name", "")
            sort_type = sd.get("type", "")
            deps = []
            if sort_type.startswith("ArraySort("):
                inner = sort_type[len("ArraySort(") : -1]
                parts = [s.strip() for s in inner.split(",")]
                deps.extend(parts)
            dependencies[name] = deps

        # Kahn's algorithm
        in_degree = {
            name: len([d for d in deps if d in dependencies]) for name, deps in dependencies.items()
        }
        queue = [name for name, deg in in_degree.items() if deg == 0]
        sorted_names = []

        while queue:
            current = queue.pop(0)
            sorted_names.append(current)
            for name, deps in dependencies.items():
                if current in deps and name not in sorted_names:
                    in_degree[name] -= 1
                    if in_degree[name] == 0:
                        queue.append(name)

        name_to_def = {sd["name"]: sd for sd in sort_defs if "name" in sd}
        return [name_to_def[n] for n in sorted_names if n in name_to_def]

    def _create_sort(self, sort_def: dict, ctx: ConversionContext) -> SMTSort:
        """Create SMTSort from definition."""
        name = sort_def["name"]
        sort_type = sort_def["type"]

        if sort_type == "DeclareSort":
            return SMTSort(
                name=name,
                kind=SMTSortKind.UNINTERPRETED,
                smt_name=name,
                smt_code=f"(declare-sort {name} 0)",
            )
        elif sort_type == "EnumSort":
            values = sort_def.get("values", [])
            constructors = " ".join(f"({v})" for v in values)
            return SMTSort(
                name=name,
                kind=SMTSortKind.ENUM,
                smt_name=name,
                params={"values": values},
                smt_code=f"(declare-datatypes (({name} 0)) ((({name} {constructors}))))",
            )
        elif sort_type.startswith("BitVecSort("):
            size = int(sort_type[len("BitVecSort(") : -1])
            return SMTSort(
                name=name,
                kind=SMTSortKind.BITVEC,
                smt_name=f"(_ BitVec {size})",
                params={"size": size},
                smt_code="",  # BitVec sorts don't need declaration
            )
        elif sort_type.startswith("ArraySort("):
            inner = sort_type[len("ArraySort(") : -1]
            domain, range_ = [s.strip() for s in inner.split(",")]
            domain_smt = ctx.resolve_sort_name(domain)
            range_smt = ctx.resolve_sort_name(range_)
            return SMTSort(
                name=name,
                kind=SMTSortKind.ARRAY,
                smt_name=f"(Array {domain_smt} {range_smt})",
                params={"domain": domain, "range": range_},
                smt_code="",  # Array sorts don't need declaration
            )
        elif sort_type in ("IntSort", "Int"):
            return SMTSort(name=name, kind=SMTSortKind.BUILTIN, smt_name="Int", smt_code="")
        elif sort_type in ("RealSort", "Real"):
            return SMTSort(name=name, kind=SMTSortKind.BUILTIN, smt_name="Real", smt_code="")
        elif sort_type in ("BoolSort", "Bool"):
            return SMTSort(name=name, kind=SMTSortKind.BUILTIN, smt_name="Bool", smt_code="")
        else:
            raise ValueError(f"Unknown sort type: {sort_type}")


class FunctionsStage(PipelineStage):
    """Stage 3: Process and emit function declarations."""

    @property
    def name(self) -> str:
        return "functions"

    def process(self, ctx: ConversionContext, config: dict[str, Any]) -> str:
        func_defs = config.get("functions", [])
        if not func_defs:
            return ""

        lines = ["; --- Functions ---"]

        for func_def in func_defs:
            smt_func = self._create_function(func_def, ctx)
            ctx.functions[smt_func.name] = smt_func
            lines.append(smt_func.smt_code)
            smt_func.emitted = True

        return "\n".join(lines) + "\n" if len(lines) > 1 else ""

    def _create_function(self, func_def: dict, ctx: ConversionContext) -> SMTFunction:
        """Create SMTFunction from definition."""
        name = func_def["name"]
        domain = func_def.get("domain", [])
        range_sort = func_def["range"]

        # Resolve sort names to SMT-LIB names
        domain_smt = [ctx.resolve_sort_name(s) for s in domain]
        range_smt = ctx.resolve_sort_name(range_sort)

        domain_str = " ".join(domain_smt) if domain_smt else ""
        smt_code = f"(declare-fun {name} ({domain_str}) {range_smt})"

        return SMTFunction(
            name=name,
            smt_name=name,
            domain=domain,
            range_sort=range_sort,
            smt_code=smt_code,
        )


class ConstantsStage(PipelineStage):
    """Stage 4: Process and emit constant declarations."""

    @property
    def name(self) -> str:
        return "constants"

    def process(self, ctx: ConversionContext, config: dict[str, Any]) -> str:
        const_defs = config.get("constants", {})
        if not const_defs:
            return ""

        lines = ["; --- Constants ---"]

        for _category, const_info in const_defs.items():
            sort_name = const_info["sort"]
            members = const_info["members"]

            # Resolve sort to SMT-LIB name
            smt_sort = ctx.resolve_sort_name(sort_name)

            if isinstance(members, list):
                for member in members:
                    smt_const = SMTConstant(
                        name=member,
                        smt_name=member,
                        sort=sort_name,
                        smt_code=f"(declare-const {member} {smt_sort})",
                    )
                    ctx.constants[member] = smt_const
                    lines.append(smt_const.smt_code)
                    smt_const.emitted = True
            elif isinstance(members, dict):
                for key in members.keys():
                    smt_const = SMTConstant(
                        name=key,
                        smt_name=key,
                        sort=sort_name,
                        smt_code=f"(declare-const {key} {smt_sort})",
                    )
                    ctx.constants[key] = smt_const
                    lines.append(smt_const.smt_code)
                    smt_const.emitted = True

        return "\n".join(lines) + "\n" if len(lines) > 1 else ""


class VariablesStage(PipelineStage):
    """Stage 5: Register variables (for use in quantifiers)."""

    @property
    def name(self) -> str:
        return "variables"

    def process(self, ctx: ConversionContext, config: dict[str, Any]) -> str:
        var_defs = config.get("variables", [])
        if not var_defs:
            return ""

        # Variables are not emitted directly - they're used in quantifiers
        # We just register them in the context for sort lookup
        for var_def in var_defs:
            name = var_def["name"]
            sort_name = var_def["sort"]
            ctx.variables[name] = sort_name

        # Return a comment indicating registered variables
        var_names = [v["name"] for v in var_defs]
        return f"; Variables registered: {', '.join(var_names)}\n" if var_names else ""


class KnowledgeBaseStage(PipelineStage):
    """Stage 6: Process and emit knowledge base assertions."""

    @property
    def name(self) -> str:
        return "knowledge_base"

    def process(self, ctx: ConversionContext, config: dict[str, Any]) -> str:
        from z3adapter.backends.smt2.emitter import ExpressionEmitter

        kb = config.get("knowledge_base", [])
        if not kb:
            return ""

        emitter = ExpressionEmitter(ctx)
        lines = ["; --- Knowledge Base ---"]

        for i, assertion in enumerate(kb):
            if isinstance(assertion, dict):
                expr_str = assertion["assertion"]
                value = assertion.get("value", True)
            else:
                expr_str = assertion
                value = True

            smt_expr = emitter.emit(expr_str)
            if not value:
                smt_expr = f"(not {smt_expr})"

            assertion_id = f"kb_{i}"
            smt_assertion = SMTAssertion(
                id=assertion_id,
                dsl_expr=expr_str,
                smt_expr=smt_expr,
                smt_code=f"(assert {smt_expr})",
            )
            ctx.kb_assertions[assertion_id] = smt_assertion
            lines.append(smt_assertion.smt_code)
            smt_assertion.emitted = True

        return "\n".join(lines) + "\n" if len(lines) > 1 else ""


class RulesStage(PipelineStage):
    """Stage 7: Process and emit rules (quantified assertions)."""

    @property
    def name(self) -> str:
        return "rules"

    def process(self, ctx: ConversionContext, config: dict[str, Any]) -> str:
        from z3adapter.backends.smt2.emitter import ExpressionEmitter

        rules = config.get("rules", [])
        if not rules:
            return ""

        emitter = ExpressionEmitter(ctx)
        lines = ["; --- Rules ---"]

        for i, rule in enumerate(rules):
            forall_vars = rule.get("forall", [])

            # Build variable bindings
            var_bindings = []
            for v in forall_vars:
                sort_name = v["sort"]
                smt_sort = ctx.resolve_sort_name(sort_name)
                var_bindings.append(f"({v['name']} {smt_sort})")
                # Register variable in context for expression parsing
                ctx.variables[v["name"]] = sort_name

            bindings_str = " ".join(var_bindings)

            if "implies" in rule:
                antecedent = emitter.emit(rule["implies"]["antecedent"])
                consequent = emitter.emit(rule["implies"]["consequent"])
                body = f"(=> {antecedent} {consequent})"
            elif "constraint" in rule:
                body = emitter.emit(rule["constraint"])
            else:
                continue

            if var_bindings:
                smt_code = f"(assert (forall ({bindings_str}) {body}))"
            else:
                smt_code = f"(assert {body})"

            rule_id = f"rule_{i}"
            smt_assertion = SMTAssertion(
                id=rule_id,
                dsl_expr=str(rule),
                smt_expr=body,
                smt_code=smt_code,
            )
            ctx.rules[rule_id] = smt_assertion
            lines.append(smt_assertion.smt_code)
            smt_assertion.emitted = True

        return "\n".join(lines) + "\n" if len(lines) > 1 else ""


class VerificationsStage(PipelineStage):
    """Stage 8: Process verifications and emit queries."""

    @property
    def name(self) -> str:
        return "verifications"

    def process(self, ctx: ConversionContext, config: dict[str, Any]) -> str:
        from z3adapter.backends.smt2.emitter import ExpressionEmitter

        verifications = config.get("verifications", [])
        if not verifications:
            return ""

        emitter = ExpressionEmitter(ctx)
        lines = ["; --- Verifications ---"]

        for i, verif in enumerate(verifications):
            name = verif.get("name", f"verification_{i}")
            query_id = f"query_{i}"

            # Save variable state before each verification to avoid pollution
            saved_variables = dict(ctx.variables)

            # Handle different verification types
            if "exists" in verif:
                # Existential verification
                exists_vars = verif["exists"]
                var_bindings = []
                for v in exists_vars:
                    sort_name = v["sort"]
                    smt_sort = ctx.resolve_sort_name(sort_name)
                    var_bindings.append(f"({v['name']} {smt_sort})")
                    ctx.variables[v["name"]] = sort_name

                constraint = emitter.emit(verif["constraint"])
                bindings_str = " ".join(var_bindings)
                smt_expr = f"(exists ({bindings_str}) {constraint})"

            elif "forall" in verif:
                # Universal verification with implication
                forall_vars = verif["forall"]
                var_bindings = []
                for v in forall_vars:
                    sort_name = v["sort"]
                    smt_sort = ctx.resolve_sort_name(sort_name)
                    var_bindings.append(f"({v['name']} {smt_sort})")
                    ctx.variables[v["name"]] = sort_name

                antecedent = emitter.emit(verif["implies"]["antecedent"])
                consequent = emitter.emit(verif["implies"]["consequent"])
                bindings_str = " ".join(var_bindings)
                smt_expr = f"(forall ({bindings_str}) (=> {antecedent} {consequent}))"

            elif "constraint" in verif:
                # Simple constraint verification
                smt_expr = emitter.emit(verif["constraint"])
            else:
                # Restore variables before continuing
                ctx.variables = saved_variables
                continue

            # Restore variable state after emitting this verification
            ctx.variables = saved_variables

            # Create scenario assertion for this query
            scenario_id = f"scenario_{i}"
            smt_assertion = SMTAssertion(
                id=scenario_id,
                dsl_expr=str(verif),
                smt_expr=smt_expr,
                label=name,
                smt_code=f"(assert {smt_expr})",
            )
            ctx.scenario_assertions[scenario_id] = smt_assertion

            # Create query
            query = SMTQuery(
                id=query_id,
                name=name,
                assertions=[scenario_id],
                check_model=True,
            )
            ctx.queries[query_id] = query

            # Emit push/pop block for isolation
            lines.append(f"; Query: {name}")
            lines.append("(push 1)")
            lines.append(smt_assertion.smt_code)
            lines.append("(check-sat)")
            lines.append("(get-model)")
            lines.append("(pop 1)")
            lines.append("")

            smt_assertion.emitted = True
            query.emitted = True

        return "\n".join(lines) if lines else ""


class Pipeline:
    """
    Composable pipeline for SMT-LIB generation.

    Stages can be selectively executed to build partial programs
    or to reuse foundations for multiple queries.
    """

    DEFAULT_STAGES = [
        LogicStage(),
        SortsStage(),
        FunctionsStage(),
        ConstantsStage(),
        VariablesStage(),
        KnowledgeBaseStage(),
        RulesStage(),
        VerificationsStage(),
    ]

    def __init__(self, stages: list[PipelineStage] | None = None) -> None:
        self.stages = stages or self.DEFAULT_STAGES.copy()
        self.ctx = ConversionContext()

    def run(self, config: dict[str, Any]) -> str:
        """Run all stages and return complete SMT-LIB program."""
        parts = []
        for stage in self.stages:
            output = stage.process(self.ctx, config)
            if output:
                parts.append(output)
        return "\n".join(parts)

    def run_stage(self, stage_name: str, config: dict[str, Any]) -> str:
        """Run a specific stage by name."""
        for stage in self.stages:
            if stage.name == stage_name:
                return stage.process(self.ctx, config)
        raise ValueError(f"Unknown stage: {stage_name}")

    def run_through(self, stage_name: str, config: dict[str, Any]) -> str:
        """Run all stages up to and including the named stage."""
        parts = []
        for stage in self.stages:
            output = stage.process(self.ctx, config)
            if output:
                parts.append(output)
            if stage.name == stage_name:
                break
        return "\n".join(parts)

    def get_context(self) -> ConversionContext:
        """Get the current conversion context."""
        return self.ctx

    def reset(self) -> None:
        """Reset the context for a new program."""
        self.ctx = ConversionContext()
