"""Expression parsing and evaluation."""

import logging
from typing import Any

from z3 import (
    And,
    Array,
    BitVecVal,
    Const,
    Distinct,
    Exists,
    ExprRef,
    ForAll,
    Function,
    If,
    Implies,
    Not,
    Or,
    Product,
    Sum,
)

from z3adapter.security.validator import ExpressionValidator

logger = logging.getLogger(__name__)


class ExpressionParser:
    """Parses and evaluates Z3 expressions from strings."""

    # Safe Z3 operators allowed in expressions
    Z3_OPERATORS = {
        "And": And,
        "Or": Or,
        "Not": Not,
        "Implies": Implies,
        "If": If,
        "Distinct": Distinct,
        "Sum": Sum,
        "Product": Product,
        "ForAll": ForAll,
        "Exists": Exists,
        "Function": Function,
        "Array": Array,
        "BitVecVal": BitVecVal,
    }

    def __init__(
        self, functions: dict[str, Any], constants: dict[str, Any], variables: dict[str, Any]
    ):
        """Initialize expression parser.

        Args:
            functions: Z3 function declarations
            constants: Z3 constants
            variables: Z3 variables
        """
        self.functions = functions
        self.constants = constants
        self.variables = variables
        self._context_cache: dict[str, Any] | None = None
        self._symbols_loaded = False

    def mark_symbols_loaded(self) -> None:
        """Mark that all symbols have been loaded and enable caching."""
        self._symbols_loaded = True

    def build_context(self, quantified_vars: list[ExprRef] | None = None) -> dict[str, Any]:
        """Build evaluation context with all defined symbols.

        Args:
            quantified_vars: Optional quantified variables to include

        Returns:
            Dictionary mapping names to Z3 objects
        """
        # Only cache context after all symbols have been loaded
        if self._context_cache is None and self._symbols_loaded:
            # Build base context once (after all sorts, functions, constants, variables loaded)
            self._context_cache = {}
            self._context_cache.update(self.functions)
            self._context_cache.update(self.constants)
            self._context_cache.update(self.variables)

        # If not cached yet, build context dynamically
        if self._context_cache is None:
            context = {}
            context.update(self.functions)
            context.update(self.constants)
            context.update(self.variables)
        else:
            context = self._context_cache.copy()

        if not quantified_vars:
            return context

        # Add quantified variables to context
        # Check for shadowing
        for v in quantified_vars:
            var_name = v.decl().name()
            if var_name in context and var_name not in [
                vv.decl().name() for vv in quantified_vars[: quantified_vars.index(v)]
            ]:
                logger.warning(f"Quantified variable '{var_name}' shadows existing symbol")
            context[var_name] = v
        return context

    def parse_expression(
        self, expr_str: str, quantified_vars: list[ExprRef] | None = None
    ) -> ExprRef:
        """Parse expression string into Z3 expression.

        Args:
            expr_str: Expression string to parse
            quantified_vars: Optional list of quantified variables

        Returns:
            Parsed Z3 expression

        Raises:
            ValueError: If expression cannot be parsed
        """
        context = self.build_context(quantified_vars)
        safe_globals = {**self.Z3_OPERATORS, **self.functions}
        return ExpressionValidator.safe_eval(expr_str, safe_globals, context)

    def add_knowledge_base(self, solver: Any, knowledge_base: list[Any]) -> None:
        """Add knowledge base assertions to solver.

        Args:
            solver: Solver instance
            knowledge_base: List of assertions

        Raises:
            ValueError: If assertion is invalid
        """
        context = self.build_context()
        safe_globals = {**self.Z3_OPERATORS, **self.functions}

        for assertion_entry in knowledge_base:
            if isinstance(assertion_entry, dict):
                assertion_str = assertion_entry["assertion"]
                value = assertion_entry.get("value", True)
            else:
                assertion_str = assertion_entry
                value = True

            try:
                expr = ExpressionValidator.safe_eval(assertion_str, safe_globals, context)
                if not value:
                    expr = Not(expr)
                solver.add(expr)
                logger.debug(f"Added knowledge base assertion: {assertion_str[:50]}...")
            except Exception as e:
                logger.error(f"Error parsing assertion '{assertion_str}': {e}")
                raise

    def add_rules(self, solver: Any, rules: list[dict[str, Any]], sorts: dict[str, Any]) -> None:
        """Add logical rules to solver.

        Args:
            solver: Solver instance
            rules: List of rule definitions
            sorts: Z3 sorts dictionary

        Raises:
            ValueError: If rule is invalid
        """
        for rule in rules:
            try:
                forall_vars = rule.get("forall", [])

                # Validate that if forall is specified, it's not empty
                if "forall" in rule and not forall_vars:
                    raise ValueError(
                        "Empty 'forall' list in rule - remove 'forall' key if no quantification needed"
                    )

                variables = [Const(v["name"], sorts[v["sort"]]) for v in forall_vars]

                if "implies" in rule:
                    if not variables:
                        raise ValueError(
                            "Implication rules require quantified variables - use 'forall' key"
                        )
                    antecedent = self.parse_expression(rule["implies"]["antecedent"], variables)
                    consequent = self.parse_expression(rule["implies"]["consequent"], variables)
                    solver.add(ForAll(variables, Implies(antecedent, consequent)))
                    logger.debug(f"Added implication rule with {len(variables)} variables")
                elif "constraint" in rule:
                    constraint = self.parse_expression(rule["constraint"], variables)
                    if variables:
                        solver.add(ForAll(variables, constraint))
                    else:
                        solver.add(constraint)
                    logger.debug("Added constraint rule")
                else:
                    raise ValueError(
                        f"Invalid rule (must contain 'implies' or 'constraint'): {rule}"
                    )
            except Exception as e:
                logger.error(f"Error adding rule: {e}")
                raise
