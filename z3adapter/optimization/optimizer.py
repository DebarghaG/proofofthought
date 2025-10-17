"""Optimization problem solver."""

import logging
from typing import Any

from z3 import Const, Optimize, sat

from z3adapter.security.validator import ExpressionValidator

logger = logging.getLogger(__name__)


class OptimizerRunner:
    """Handles optimization problem setup and solving."""

    def __init__(
        self, expression_parser: Any, sorts: dict[str, Any], z3_operators: dict[str, Any]
    ) -> None:
        """Initialize optimizer runner.

        Args:
            expression_parser: ExpressionParser instance
            sorts: Z3 sorts dictionary
            z3_operators: Dictionary of Z3 operators
        """
        self.expression_parser = expression_parser
        self.sorts = sorts
        self.z3_operators = z3_operators
        self.optimizer = Optimize()

    def optimize(self, optimization_config: dict[str, Any], optimize_timeout: int) -> None:
        """Run optimization if defined in configuration.

        Args:
            optimization_config: Optimization configuration
            optimize_timeout: Timeout in milliseconds

        The optimizer is separate from the solver and doesn't share constraints.
        This is intentional to allow independent optimization problems.
        """
        if not optimization_config:
            logger.info("No optimization section found.")
            return

        logger.info("Running optimization")

        try:
            # Create variables for optimization
            optimization_vars = {}
            for var_def in optimization_config.get("variables", []):
                name = var_def["name"]
                sort_name = var_def["sort"]
                if sort_name not in self.sorts:
                    raise ValueError(f"Sort '{sort_name}' not defined")
                sort = self.sorts[sort_name]
                optimization_vars[name] = Const(name, sort)

            # Build extended context: optimization variables + global context
            # This allows optimization constraints to reference knowledge base constants
            base_context = self.expression_parser.build_context()
            opt_context = {**base_context, **optimization_vars}

            # Combine Z3 operators with functions
            safe_globals = {**self.z3_operators, **self.expression_parser.functions}

            # Add constraints - they can now reference both opt vars and global symbols
            for constraint in optimization_config.get("constraints", []):
                expr = ExpressionValidator.safe_eval(constraint, safe_globals, opt_context)
                self.optimizer.add(expr)
                logger.debug(f"Added optimization constraint: {constraint[:50]}...")

            # Add objectives
            for objective in optimization_config.get("objectives", []):
                expr = ExpressionValidator.safe_eval(
                    objective["expression"], safe_globals, opt_context
                )
                if objective["type"] == "maximize":
                    self.optimizer.maximize(expr)
                    logger.debug(f"Maximizing: {objective['expression']}")
                elif objective["type"] == "minimize":
                    self.optimizer.minimize(expr)
                    logger.debug(f"Minimizing: {objective['expression']}")
                else:
                    logger.warning(f"Unknown optimization type: {objective['type']}")

            self.optimizer.set("timeout", optimize_timeout)
            result = self.optimizer.check()

            if result == sat:
                model = self.optimizer.model()
                logger.info(f"Optimal Model: {model}")
            else:
                logger.warning("No optimal solution found.")
        except Exception as e:
            logger.error(f"Error during optimization: {e}")
            raise
