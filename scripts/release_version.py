#!/usr/bin/env python3
"""Utilities for stamping nightly release versions."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def load_version_module():
    """Load the version helper module without importing the package __init__."""
    version_module_path = Path(__file__).resolve().parents[1] / "z3adapter" / "_version.py"
    spec = importlib.util.spec_from_file_location("proofofthought_version", version_module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load version helpers from {version_module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rewrite_version_file(path: Path, version: str) -> None:
    """Rewrite the package version file to the provided explicit version."""
    path.write_text(f"{version}\n")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("base", help="Print the stable base version")

    nightly_parser = subparsers.add_parser("nightly", help="Print a nightly prerelease version")
    nightly_parser.add_argument(
        "--stamp",
        type=str,
        default=None,
        help="UTC timestamp stamp in YYYYMMDDHHMM format; defaults to the current UTC time",
    )

    write_parser = subparsers.add_parser(
        "write", help="Rewrite the version file with an explicit version string"
    )
    write_parser.add_argument("--version", required=True, help="Version string to write")
    write_parser.add_argument(
        "--path",
        type=Path,
        default=Path("z3adapter/VERSION"),
        help="Path to the version file to rewrite",
    )

    return parser.parse_args()


def main() -> None:
    """Run the selected command."""
    args = parse_args()
    version_module = load_version_module()
    if args.command == "base":
        print(version_module.stable_base_version(version_module.BASE_VERSION))
        return
    if args.command == "nightly":
        stamp = args.stamp or version_module.utc_nightly_stamp()
        print(version_module.build_nightly_version(stamp))
        return
    rewrite_version_file(args.path, args.version)
    print(args.version)


if __name__ == "__main__":
    main()
