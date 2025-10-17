"""Sort creation and management."""

import logging
from typing import Any

from z3 import (
    ArraySort,
    BitVecSort,
    BoolSort,
    Const,
    DeclareSort,
    EnumSort,
    IntSort,
    RealSort,
    SortRef,
)

logger = logging.getLogger(__name__)


class SortManager:
    """Manages Z3 sort creation and dependencies."""

    MAX_BITVEC_SIZE = 65536  # Maximum reasonable bitvector size

    def __init__(self) -> None:
        self.sorts: dict[str, SortRef] = {}
        self.constants: dict[str, Any] = {}
        self._initialize_builtin_sorts()

    def _initialize_builtin_sorts(self) -> None:
        """Initialize built-in Z3 sorts."""
        built_in_sorts = {"BoolSort": BoolSort(), "IntSort": IntSort(), "RealSort": RealSort()}
        self.sorts.update(built_in_sorts)

    @staticmethod
    def _topological_sort_sorts(sort_defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Topologically sort sort definitions to handle dependencies.

        Args:
            sort_defs: List of sort definitions

        Returns:
            Sorted list where dependencies come before dependents

        Raises:
            ValueError: If circular dependency detected or missing name field
        """
        # Build dependency graph
        dependencies = {}
        for sort_def in sort_defs:
            if "name" not in sort_def:
                raise ValueError(f"Sort definition missing 'name' field: {sort_def}")
            name = sort_def["name"]
            sort_type = sort_def["type"]
            deps = []

            # Extract dependencies based on sort type
            if sort_type.startswith("ArraySort("):
                domain_range = sort_type[len("ArraySort(") : -1]
                parts = [s.strip() for s in domain_range.split(",")]
                deps.extend(parts)

            dependencies[name] = deps

        # Perform topological sort using Kahn's algorithm
        # in_degree = number of dependencies a sort has
        in_degree = {}
        for name, deps in dependencies.items():
            # Count only user-defined dependencies (not built-ins)
            user_deps = [d for d in deps if d in dependencies]
            in_degree[name] = len(user_deps)

        # Start with nodes that have no dependencies
        queue = [name for name, degree in in_degree.items() if degree == 0]
        sorted_names = []

        while queue:
            current = queue.pop(0)
            sorted_names.append(current)

            # Reduce in-degree for sorts that depend on current
            for name, deps in dependencies.items():
                if current in deps and name not in sorted_names:
                    in_degree[name] -= 1
                    if in_degree[name] == 0:
                        queue.append(name)

        # Check for cycles
        if len(sorted_names) != len(dependencies):
            remaining = set(dependencies.keys()) - set(sorted_names)
            raise ValueError(f"Circular dependency detected in sorts: {remaining}")

        # Reorder sort_defs according to sorted_names
        name_to_def = {s["name"]: s for s in sort_defs}
        return [name_to_def[name] for name in sorted_names]

    def create_sorts(self, sort_defs: list[dict[str, Any]]) -> None:
        """Create Z3 sorts from definitions.

        Args:
            sort_defs: List of sort definitions

        Raises:
            ValueError: If sort definition is invalid
        """
        # Topologically sort sorts to handle dependencies
        sorted_sort_defs = self._topological_sort_sorts(sort_defs)

        # Create user-defined sorts in dependency order
        for sort_def in sorted_sort_defs:
            try:
                name = sort_def["name"]
                sort_type = sort_def["type"]

                if sort_type == "EnumSort":
                    values = sort_def["values"]
                    enum_sort, enum_consts = EnumSort(name, values)
                    self.sorts[name] = enum_sort
                    # Add enum constants to context
                    for val_name, const in zip(values, enum_consts, strict=False):
                        self.constants[val_name] = const
                elif sort_type.startswith("BitVecSort("):
                    size_str = sort_type[len("BitVecSort(") : -1].strip()
                    try:
                        size = int(size_str)
                        if size <= 0:
                            raise ValueError(f"BitVecSort size must be positive, got {size}")
                        if size > self.MAX_BITVEC_SIZE:
                            raise ValueError(
                                f"BitVecSort size {size} exceeds maximum {self.MAX_BITVEC_SIZE}"
                            )
                        self.sorts[name] = BitVecSort(size)
                    except ValueError as e:
                        raise ValueError(f"Invalid BitVecSort size '{size_str}': {e}") from e
                elif sort_type.startswith("ArraySort("):
                    domain_range = sort_type[len("ArraySort(") : -1]
                    domain_sort_name, range_sort_name = [s.strip() for s in domain_range.split(",")]
                    domain_sort = self.sorts.get(domain_sort_name)
                    range_sort = self.sorts.get(range_sort_name)
                    if domain_sort is None or range_sort is None:
                        raise ValueError(
                            f"ArraySort references undefined sorts: {domain_sort_name}, {range_sort_name}"
                        )
                    self.sorts[name] = ArraySort(domain_sort, range_sort)
                elif sort_type == "IntSort":
                    self.sorts[name] = IntSort()
                elif sort_type == "RealSort":
                    self.sorts[name] = RealSort()
                elif sort_type == "BoolSort":
                    self.sorts[name] = BoolSort()
                elif sort_type == "DeclareSort":
                    self.sorts[name] = DeclareSort(name)
                else:
                    raise ValueError(f"Unknown sort type: {sort_type}")
                logger.debug(f"Created sort: {name} ({sort_type})")
            except KeyError as e:
                logger.error(f"Missing required field in sort definition: {e}")
                raise ValueError(f"Invalid sort definition {sort_def}: missing {e}") from e
            except Exception as e:
                logger.error(f"Error creating sort '{name}': {e}")
                raise

    def create_functions(self, func_defs: list[dict[str, Any]]) -> dict[str, Any]:
        """Create Z3 functions from definitions.

        Args:
            func_defs: List of function definitions

        Returns:
            Dictionary mapping function names to Z3 function declarations

        Raises:
            ValueError: If function definition is invalid
        """
        from z3 import Function

        functions = {}
        for func_def in func_defs:
            try:
                name = func_def["name"]
                # Validate domain sorts exist
                for sort_name in func_def["domain"]:
                    if sort_name not in self.sorts:
                        raise ValueError(f"Sort '{sort_name}' not defined")
                domain = [self.sorts[sort] for sort in func_def["domain"]]
                # Validate range sort exists
                range_sort_name = func_def["range"]
                if range_sort_name not in self.sorts:
                    raise ValueError(f"Sort '{range_sort_name}' not defined")
                range_sort = self.sorts[range_sort_name]
                functions[name] = Function(name, *domain, range_sort)
                logger.debug(f"Created function: {name}")
            except KeyError as e:
                logger.error(f"Missing required field in function definition: {e}")
                raise ValueError(f"Invalid function definition {func_def}: missing {e}") from e
            except Exception as e:
                logger.error(f"Error creating function '{name}': {e}")
                raise
        return functions

    def create_constants(self, constants_defs: dict[str, Any]) -> None:
        """Create Z3 constants from definitions.

        Args:
            constants_defs: Dictionary of constant definitions

        Raises:
            ValueError: If constant definition is invalid
        """
        for category, constants in constants_defs.items():
            try:
                sort_name = constants["sort"]
                if sort_name not in self.sorts:
                    raise ValueError(f"Sort '{sort_name}' not defined")

                if isinstance(constants["members"], list):
                    # List format: ["name1", "name2"] -> create constants with those names
                    self.constants.update(
                        {c: Const(c, self.sorts[sort_name]) for c in constants["members"]}
                    )
                elif isinstance(constants["members"], dict):
                    # Dict format: {"ref_name": "z3_name"} -> create constant with z3_name
                    # FIX: Use key as both reference name AND Z3 constant name for consistency
                    self.constants.update(
                        {
                            k: Const(k, self.sorts[sort_name])
                            for k, v in constants["members"].items()
                        }
                    )
                    logger.debug(
                        "Note: Dict values in constants are deprecated, using keys as Z3 names"
                    )
                else:
                    logger.warning(f"Invalid members format for category '{category}', skipping")
                logger.debug(f"Created constants for category: {category}")
            except KeyError as e:
                logger.error(
                    f"Missing required field in constants definition for '{category}': {e}"
                )
                raise ValueError(f"Invalid constants definition: missing {e}") from e
            except Exception as e:
                logger.error(f"Error creating constants for category '{category}': {e}")
                raise

    def create_variables(self, var_defs: list[dict[str, Any]]) -> dict[str, Any]:
        """Create Z3 variables from definitions.

        Args:
            var_defs: List of variable definitions

        Returns:
            Dictionary mapping variable names to Z3 constants

        Raises:
            ValueError: If variable definition is invalid
        """
        variables = {}
        for var_def in var_defs:
            try:
                name = var_def["name"]
                sort_name = var_def["sort"]
                if sort_name not in self.sorts:
                    raise ValueError(f"Sort '{sort_name}' not defined")
                sort = self.sorts[sort_name]
                variables[name] = Const(name, sort)
                logger.debug(f"Created variable: {name} of sort {sort_name}")
            except KeyError as e:
                logger.error(f"Missing required field in variable definition: {e}")
                raise ValueError(f"Invalid variable definition {var_def}: missing {e}") from e
            except Exception as e:
                logger.error(f"Error creating variable '{name}': {e}")
                raise
        return variables
