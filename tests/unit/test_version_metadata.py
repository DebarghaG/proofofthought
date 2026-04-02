"""Unit tests for package version helpers and metadata consistency."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib

from z3adapter._version import (
    BASE_VERSION,
    __version__,
    build_nightly_version,
    stable_base_version,
    utc_nightly_stamp,
)


class TestVersionMetadata(unittest.TestCase):
    """Validate version helper behavior."""

    def test_runtime_version_matches_base_version(self) -> None:
        """The checked-in runtime version should match the stable base version."""
        self.assertEqual(__version__, BASE_VERSION)

    def test_nightly_version_uses_dev_release_format(self) -> None:
        """Nightly version strings should be valid prerelease versions."""
        self.assertEqual(build_nightly_version("202604011230"), f"{BASE_VERSION}.dev202604011230")

    def test_nightly_version_rejects_invalid_stamps(self) -> None:
        """Nightly stamps must be a 12-digit UTC timestamp."""
        with self.assertRaises(ValueError):
            build_nightly_version("2026-04-01")

    def test_nightly_stamp_is_utc(self) -> None:
        """Timestamp generation should normalize to UTC."""
        now = datetime(2026, 4, 1, 8, 15, tzinfo=timezone.utc)
        self.assertEqual(utc_nightly_stamp(now), "202604010815")

    def test_stable_base_version_strips_existing_dev_suffix(self) -> None:
        """Nightly stamping should stay stable if rerun against a stamped checkout."""
        self.assertEqual(stable_base_version("1.0.1.dev202604011230"), "1.0.1")

    def test_pyproject_uses_dynamic_version_metadata(self) -> None:
        """Packaging metadata should source the version from the package module."""
        pyproject = tomllib.loads(Path("pyproject.toml").read_text())
        self.assertEqual(pyproject["project"]["dynamic"], ["version"])
        self.assertEqual(
            pyproject["tool"]["setuptools"]["dynamic"]["version"]["file"],
            ["z3adapter/VERSION"],
        )
        self.assertEqual(pyproject["project"]["requires-python"], ">=3.10,<3.14")
        self.assertEqual(
            pyproject["tool"]["setuptools"]["packages"]["find"]["include"],
            ["proofofthought*", "z3adapter*"],
        )


if __name__ == "__main__":
    unittest.main()
