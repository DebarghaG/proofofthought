"""Verification condition checker."""

import logging
from typing import Any

from z3 import Const, Exists, ExprRef, ForAll, Implies, sat, unsat

logger = logging.getLogger(__name__)


class Verifier:
    """Handles verification condition creation and checking."""

    def __init__(self, expression_parser: Any, sorts: dict[str, Any]) -> None:
        """Initialize verifier.

        Args:
            expression_parser: ExpressionParser instance
            sorts: Z3 sorts dictionary
        """
        self.expression_parser = expression_parser
        self.sorts = sorts
        self.verifications: dict[str, ExprRef] = {}
        self.sat_count: int = 0
        self.unsat_count: int = 0

    def add_verifications(self, verification_defs: list[dict[str, Any]]) -> None:
        """Add verification conditions.

        Args:
            verification_defs: List of verification definitions

        Raises:
            ValueError: If verification is invalid
        """
        for verification in verification_defs:
            try:
                name = verification.get("name", "unnamed_verification")

                if "exists" in verification:
                    exists_vars = verification["exists"]
                    if not exists_vars:
                        raise ValueError(f"Empty 'exists' list in verification '{name}'")
                    # Validate sorts exist before creating variables
                    for v in exists_vars:
                        if v["sort"] not in self.sorts:
                            raise ValueError(f"Sort '{v['sort']}' not defined")
                    variables = [Const(v["name"], self.sorts[v["sort"]]) for v in exists_vars]
                    constraint = self.expression_parser.parse_expression(
                        verification["constraint"], variables
                    )
                    self.verifications[name] = Exists(variables, constraint)
                elif "forall" in verification:
                    forall_vars = verification["forall"]
                    if not forall_vars:
                        raise ValueError(f"Empty 'forall' list in verification '{name}'")
                    # Validate sorts exist before creating variables
                    for v in forall_vars:
                        if v["sort"] not in self.sorts:
                            raise ValueError(f"Sort '{v['sort']}' not defined")
                    variables = [Const(v["name"], self.sorts[v["sort"]]) for v in forall_vars]
                    antecedent = self.expression_parser.parse_expression(
                        verification["implies"]["antecedent"], variables
                    )
                    consequent = self.expression_parser.parse_expression(
                        verification["implies"]["consequent"], variables
                    )
                    self.verifications[name] = ForAll(variables, Implies(antecedent, consequent))
                elif "constraint" in verification:
                    # Handle constraints without quantifiers
                    constraint = self.expression_parser.parse_expression(verification["constraint"])
                    self.verifications[name] = constraint
                else:
                    raise ValueError(
                        f"Invalid verification (must contain 'exists', 'forall', or 'constraint'): {verification}"
                    )
                logger.debug(f"Added verification: {name}")
            except Exception as e:
                logger.error(
                    f"Error processing verification '{verification.get('name', 'unknown')}': {e}"
                )
                raise

    def verify_conditions(self, solver: Any, verify_timeout: int) -> None:
        """Verify all defined verification conditions.

        Args:
            solver: Solver instance
            verify_timeout: Timeout in milliseconds

        Note: This checks satisfiability (SAT means condition can be true).
        For entailment checking (knowledge_base IMPLIES condition),
        check if knowledge_base AND NOT(condition) is UNSAT.
        """
        # Reset counts at the start of verification
        self.sat_count = 0
        self.unsat_count = 0

        if not self.verifications:
            logger.info("No verifications to check")
            return

        logger.info(f"Checking {len(self.verifications)} verification condition(s)")
        solver.set("timeout", verify_timeout)

        for name, condition in self.verifications.items():
            try:
                # Use push/pop to isolate each verification check
                # This ensures verifications don't interfere with each other
                # Note: We're checking satisfiability, not entailment here
                # The condition is added AS AN ASSUMPTION to existing knowledge base
                logger.debug(f"Checking verification '{name}'")
                result = solver.check(condition)

                if result == sat:
                    self.sat_count += 1
                    model = solver.model()
                    logger.info(f"{name}: SAT")
                    logger.info(f"Model: {model}")
                elif result == unsat:
                    self.unsat_count += 1
                    logger.info(f"{name}: UNSAT (condition contradicts knowledge base)")
                else:
                    logger.warning(f"{name}: UNKNOWN (timeout or incomplete)")
            except Exception as e:
                logger.error(f"Error checking verification '{name}': {e}")
                raise
