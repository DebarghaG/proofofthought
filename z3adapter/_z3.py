"""Helpers for locating the Z3 executable in development and packaged installs."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _executable_names() -> tuple[str, ...]:
    if os.name == "nt":
        return ("z3.exe", "z3")
    return ("z3",)


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []
    executable_names = _executable_names()

    interpreter_dir = Path(sys.executable).resolve().parent
    for name in executable_names:
        candidates.append(interpreter_dir / name)

    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env:
        venv_root = Path(virtual_env)
        for subdir in ("Scripts", "bin"):
            for name in executable_names:
                candidates.append(venv_root / subdir / name)

    repo_root = Path(__file__).resolve().parents[1]
    for env_dir in ("venv", ".venv"):
        for subdir in ("Scripts", "bin"):
            for name in executable_names:
                candidates.append(repo_root / env_dir / subdir / name)

    seen: set[Path] = set()
    unique_candidates: list[Path] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique_candidates.append(candidate)
    return unique_candidates


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _not_found_message(requested_path: str, searched_paths: list[Path]) -> str:
    lines = [f"Z3 executable not found: '{requested_path}'"]
    if searched_paths:
        lines.append(
            "Searched: " + ", ".join(str(path) for path in searched_paths if str(path).strip())
        )
    lines.extend(
        [
            "Please install Z3:",
            "  - pip install z3-solver",
            "  - Or download from: https://github.com/Z3Prover/z3/releases",
            "  - Or specify a custom path with z3_path='/path/to/z3'",
        ]
    )
    return "\n".join(lines)


def resolve_z3_path(z3_path: str = "z3") -> str:
    """Resolve the Z3 executable path.

    The default lookup prefers the active PATH, then falls back to the current
    Python environment's bin/Scripts directory, followed by repo-local virtual
    environments such as ``venv/`` or ``.venv/``.
    """

    if z3_path != "z3":
        expanded = Path(z3_path).expanduser()
        if _is_executable(expanded):
            return str(expanded.resolve())
        resolved = shutil.which(z3_path)
        if resolved:
            return resolved
        raise FileNotFoundError(_not_found_message(z3_path, [expanded]))

    resolved = shutil.which("z3")
    if resolved:
        return resolved

    searched_paths = _candidate_paths()
    for candidate in searched_paths:
        if _is_executable(candidate):
            return str(candidate.resolve())

    raise FileNotFoundError(_not_found_message(z3_path, searched_paths))


def is_z3_available(z3_path: str = "z3") -> bool:
    """Return whether a usable Z3 executable can be resolved."""

    try:
        resolve_z3_path(z3_path)
    except FileNotFoundError:
        return False
    return True
