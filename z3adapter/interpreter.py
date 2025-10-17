"""Main Z3 JSON interpreter."""

import json
import logging
from typing import Any

from z3adapter.dsl.expressions import ExpressionParser
from z3adapter.dsl.sorts import SortManager
from z3adapter.optimization.optimizer import OptimizerRunner
from z3adapter.solvers.abstract import AbstractSolver
from z3adapter.solvers.z3_solver import Z3Solver
from z3adapter.verification.verifier import Verifier

logger = logging.getLogger(__name__)


class Z3JSONInterpreter:
    """Interpreter for Z3 DSL defined in JSON format."""

    # Default timeout values in milliseconds
    DEFAULT_VERIFY_TIMEOUT = 10000
    DEFAULT_OPTIMIZE_TIMEOUT = 100000

    def __init__(
        self,
        json_file: str,
        solver: AbstractSolver | None = None,
        verify_timeout: int = DEFAULT_VERIFY_TIMEOUT,
        optimize_timeout: int = DEFAULT_OPTIMIZE_TIMEOUT,
    ):
        """Initialize the Z3 JSON interpreter.

        Args:
            json_file: Path to JSON configuration file
            solver: Optional solver instance (defaults to Z3Solver)
            verify_timeout: Timeout for verification in milliseconds
            optimize_timeout: Timeout for optimization in milliseconds
        """
        self.json_file = json_file
        self.verify_timeout = verify_timeout
        self.optimize_timeout = optimize_timeout
        self.config = self.load_and_validate_json(json_file)
        self.solver = solver if solver else Z3Solver()

        # Initialize components
        self.sort_manager = SortManager()
        self.expression_parser: ExpressionParser | None = None
        self.verifier: Verifier | None = None
        self.optimizer_runner: OptimizerRunner | None = None

    def load_and_validate_json(self, json_file: str) -> dict[str, Any]:
        """Load and validate JSON configuration file.

        Args:
            json_file: Path to JSON file

        Returns:
            Validated configuration dictionary

        Raises:
            FileNotFoundError: If JSON file doesn't exist
            json.JSONDecodeError: If JSON is malformed
            ValueError: If required sections are invalid
        """
        try:
            with open(json_file) as file:
                config = json.load(file)
        except FileNotFoundError:
            logger.error(f"JSON file not found: {json_file}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {json_file}: {e}")
            raise

        # Initialize missing sections with appropriate defaults
        default_sections: dict[str, Any] = {
            "sorts": [],
            "functions": [],
            "constants": {},
            "knowledge_base": [],
            "rules": [],
            "verifications": [],
            "actions": [],
            "variables": [],
        }

        for section, default in default_sections.items():
            if section not in config:
                config[section] = default
                logger.debug(f"Section '{section}' not found, using default: {default}")

        # Validate structure
        if not isinstance(config.get("constants"), dict):
            config["constants"] = {}
            logger.warning("'constants' section should be a dictionary, resetting to empty dict")

        return config

    def perform_actions(self) -> None:
        """Execute actions specified in configuration.

        Actions are method names to be called on this interpreter instance.
        """
        for action in self.config["actions"]:
            if hasattr(self, action):
                try:
                    logger.info(f"Executing action: {action}")
                    getattr(self, action)()
                except Exception as e:
                    logger.error(f"Error executing action '{action}': {e}")
                    raise
            else:
                logger.warning(f"Unknown action: {action}")

    def verify_conditions(self) -> None:
        """Verify all defined verification conditions."""
        if self.verifier:
            self.verifier.verify_conditions(self.solver, self.verify_timeout)

    def get_verification_counts(self) -> tuple[int, int]:
        """Get SAT and UNSAT counts from verification results.

        Returns:
            Tuple of (sat_count, unsat_count)
        """
        if self.verifier:
            return (self.verifier.sat_count, self.verifier.unsat_count)
        return (0, 0)

    def optimize(self) -> None:
        """Run optimization if configured."""
        if self.optimizer_runner and "optimization" in self.config:
            self.optimizer_runner.optimize(self.config["optimization"], self.optimize_timeout)

    def run(self) -> None:
        """Execute the full interpretation pipeline.

        Steps:
        1. Create sorts
        2. Create functions
        3. Create constants
        4. Create variables
        5. Add knowledge base
        6. Add rules
        7. Add verifications
        8. Perform configured actions

        Raises:
            Various exceptions if any step fails
        """
        try:
            logger.info(f"Starting interpretation of {self.json_file}")

            # Step 1: Create sorts
            self.sort_manager.create_sorts(self.config["sorts"])

            # Step 2: Create functions
            functions = self.sort_manager.create_functions(self.config["functions"])

            # Step 3: Create constants
            self.sort_manager.create_constants(self.config["constants"])

            # Step 4: Create variables
            variables = self.sort_manager.create_variables(self.config.get("variables", []))

            # Initialize expression parser with all symbols
            self.expression_parser = ExpressionParser(
                functions=functions, constants=self.sort_manager.constants, variables=variables
            )

            # Mark that all symbols have been loaded
            self.expression_parser.mark_symbols_loaded()

            # Step 5: Add knowledge base
            self.expression_parser.add_knowledge_base(self.solver, self.config["knowledge_base"])

            # Step 6: Add rules
            self.expression_parser.add_rules(
                self.solver, self.config["rules"], self.sort_manager.sorts
            )

            # Step 7: Initialize verifier and add verifications
            self.verifier = Verifier(self.expression_parser, self.sort_manager.sorts)
            self.verifier.add_verifications(self.config["verifications"])

            # Initialize optimizer runner
            self.optimizer_runner = OptimizerRunner(
                self.expression_parser, self.sort_manager.sorts, ExpressionParser.Z3_OPERATORS
            )

            # Step 8: Perform actions
            self.perform_actions()

            logger.info("Interpretation completed successfully")
        except Exception as e:
            logger.error(f"Interpretation failed: {e}")
            raise
