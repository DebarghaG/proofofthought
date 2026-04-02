#!/usr/bin/env python3
"""Fail if release artifacts contain obvious secret material."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
import io
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import zipfile

_BLOCKED_PATH_RE = re.compile(
    r"(^|/)(\.env|\.pypirc|id_rsa|id_ed25519|secrets\.toml|credentials(\.[^/]+)?\.json)$",
    re.IGNORECASE,
)
_BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
_TEXT_EXTENSIONS = {
    ".cfg",
    ".env",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_REMOVED_RUNTIME_PATHS = {
    "z3adapter/backends/json_backend.py",
    "z3adapter/cli.py",
    "z3adapter/interpreter.py",
    "z3adapter/reasoning/prompt_template.py",
    "z3adapter/reasoning/verifier.py",
}
_REMOVED_RUNTIME_PREFIXES = (
    "z3adapter/dsl/",
    "z3adapter/optimization/",
    "z3adapter/security/",
    "z3adapter/solvers/",
    "z3adapter/verification/",
)
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"pypi-AgEI[A-Za-z0-9._-]+"), "PyPI token"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "GitHub token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key block"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "OpenAI-style API key"),
    (
        re.compile(r"OPENAI_API_KEY\s*=\s*(?!your-|<|sk-\.\.\.)\S+"),
        "OPENAI_API_KEY assignment",
    ),
    (
        re.compile(r"AZURE_OPENAI_KEY\s*=\s*(?!your-|<|\.\.\.)\S+"),
        "AZURE_OPENAI_KEY assignment",
    ),
)


def iter_artifact_paths(paths: list[str]) -> Iterator[Path]:
    """Yield artifact files from the provided path arguments."""
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file():
                    yield child
            continue
        yield path


def iter_zip_members(path: Path) -> Iterator[tuple[PurePosixPath, bytes]]:
    """Yield file members from a wheel."""
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            with archive.open(info) as member:
                yield PurePosixPath(info.filename), member.read()


def iter_tar_members(path: Path) -> Iterator[tuple[PurePosixPath, bytes]]:
    """Yield file members from a source distribution."""
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            with extracted:
                yield PurePosixPath(member.name), extracted.read()


def scan_member(member_path: PurePosixPath, data: bytes) -> list[str]:
    """Return any policy violations for a single archive member."""
    issues: list[str] = []
    normalized_path = member_path.as_posix()
    if any(
        normalized_path == removed_path or normalized_path.endswith(f"/{removed_path}")
        for removed_path in _REMOVED_RUNTIME_PATHS
    ) or any(
        normalized_path.startswith(removed_prefix) or f"/{removed_prefix}" in normalized_path
        for removed_prefix in _REMOVED_RUNTIME_PREFIXES
    ):
        issues.append(f"removed runtime module present in artifact: {normalized_path}")
        return issues
    lowered_name = member_path.name.lower()
    if _BLOCKED_PATH_RE.search(normalized_path) or member_path.suffix.lower() in _BLOCKED_SUFFIXES:
        issues.append(f"blocked file path: {normalized_path}")
        return issues
    if member_path.suffix.lower() not in _TEXT_EXTENSIONS and lowered_name not in {".env", ".pypirc"}:
        return issues
    try:
        text = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8").read()
    except UnicodeDecodeError:
        return issues
    for pattern, description in _SECRET_PATTERNS:
        if pattern.search(text):
            issues.append(f"{description} found in {normalized_path}")
    return issues


def scan_artifact(path: Path) -> list[str]:
    """Inspect a wheel or source distribution and return any issues found."""
    suffixes = path.suffixes
    if suffixes[-1:] == [".whl"]:
        members = iter_zip_members(path)
    elif suffixes[-2:] == [".tar", ".gz"]:
        members = iter_tar_members(path)
    else:
        return [f"unsupported artifact type: {path.name}"]

    issues: list[str] = []
    for member_path, data in members:
        issues.extend(scan_member(member_path, data))
    return issues


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Artifact files or directories to inspect")
    return parser.parse_args()


def main() -> int:
    """Run the artifact scanner and return a shell exit code."""
    args = parse_args()
    all_issues: list[str] = []
    for artifact_path in iter_artifact_paths(args.paths):
        if not artifact_path.exists():
            all_issues.append(f"artifact not found: {artifact_path}")
            continue
        all_issues.extend(scan_artifact(artifact_path))
    if all_issues:
        for issue in all_issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        return 1
    print("Release artifacts passed secret scan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
