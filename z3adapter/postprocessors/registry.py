"""Registry for managing postprocessor techniques."""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from z3adapter.postprocessors.abstract import Postprocessor

logger = logging.getLogger(__name__)


class PostprocessorRegistry:
    """Registry for managing and creating postprocessor instances.

    Provides a centralized way to create postprocessors by name and
    manage default configurations.

    Example:
        >>> registry = PostprocessorRegistry()
        >>> refine = registry.get("self_refine", num_iterations=3)
        >>> consistency = registry.get("self_consistency", num_samples=7)
    """

    _POSTPROCESSOR_MAP = {
        "self_refine": "z3adapter.postprocessors.self_refine.SelfRefine",
        "self_consistency": "z3adapter.postprocessors.self_consistency.SelfConsistency",
        "decomposed": "z3adapter.postprocessors.decomposed.DecomposedPrompting",
        "least_to_most": "z3adapter.postprocessors.least_to_most.LeastToMostPrompting",
    }

    # Default configurations for each postprocessor
    _DEFAULT_CONFIGS = {
        "self_refine": {"num_iterations": 2},
        "self_consistency": {"num_samples": 5},
        "decomposed": {"max_subquestions": 5},
        "least_to_most": {"max_steps": 5},
    }

    @classmethod
    def get(cls, name: str, **kwargs) -> "Postprocessor":  # type: ignore[no-untyped-def]
        """Get a postprocessor instance by name.

        Args:
            name: Postprocessor name (e.g., "self_refine", "self_consistency")
            **kwargs: Configuration parameters to override defaults

        Returns:
            Postprocessor instance

        Raises:
            ValueError: If postprocessor name is not registered
            ImportError: If postprocessor module cannot be imported
        """
        if name not in cls._POSTPROCESSOR_MAP:
            available = ", ".join(cls._POSTPROCESSOR_MAP.keys())
            raise ValueError(
                f"Unknown postprocessor: '{name}'. " f"Available postprocessors: {available}"
            )

        # Get class path and import
        class_path = cls._POSTPROCESSOR_MAP[name]
        module_path, class_name = class_path.rsplit(".", 1)

        try:
            import importlib

            module = importlib.import_module(module_path)
            postprocessor_class = getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            raise ImportError(f"Failed to import postprocessor '{name}': {e}") from e

        # Merge default config with kwargs
        config = cls._DEFAULT_CONFIGS.get(name, {}).copy()
        config.update(kwargs)

        logger.debug(f"Creating postprocessor '{name}' with config: {config}")
        return postprocessor_class(**config)

    @classmethod
    def get_multiple(cls, names: list[str], configs: dict | None = None) -> list["Postprocessor"]:
        """Get multiple postprocessor instances.

        Args:
            names: List of postprocessor names
            configs: Optional dict mapping names to config dicts

        Returns:
            List of postprocessor instances

        Example:
            >>> registry = PostprocessorRegistry()
            >>> postprocessors = registry.get_multiple(
            ...     ["self_refine", "self_consistency"],
            ...     {"self_refine": {"num_iterations": 3}}
            ... )
        """
        configs = configs or {}
        postprocessors = []

        for name in names:
            config = configs.get(name, {})
            postprocessor = cls.get(name, **config)
            postprocessors.append(postprocessor)

        return postprocessors

    @classmethod
    def list_available(cls) -> list[str]:
        """List all available postprocessor names.

        Returns:
            List of registered postprocessor names
        """
        return list(cls._POSTPROCESSOR_MAP.keys())

    @classmethod
    def get_default_config(cls, name: str) -> dict:
        """Get default configuration for a postprocessor.

        Args:
            name: Postprocessor name

        Returns:
            Dictionary of default configuration parameters

        Raises:
            ValueError: If postprocessor name is not registered
        """
        if name not in cls._POSTPROCESSOR_MAP:
            available = ", ".join(cls._POSTPROCESSOR_MAP.keys())
            raise ValueError(
                f"Unknown postprocessor: '{name}'. " f"Available postprocessors: {available}"
            )

        return cls._DEFAULT_CONFIGS.get(name, {}).copy()
