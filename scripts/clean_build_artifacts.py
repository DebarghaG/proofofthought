#!/usr/bin/env python3
"""Remove generated packaging directories before building release artifacts."""

from __future__ import annotations

import shutil
from pathlib import Path


def iter_generated_paths(repo_root: Path) -> list[Path]:
    """Return known generated packaging paths under the repository root."""
    paths = [
        repo_root / "build",
        repo_root / "dist",
    ]
    paths.extend(repo_root.glob("*.egg-info"))
    return sorted(paths)


def main() -> int:
    """Delete known generated packaging paths and report what changed."""
    repo_root = Path(__file__).resolve().parent.parent
    removed_any = False

    for path in iter_generated_paths(repo_root):
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed_any = True
        print(f"Removed {path.relative_to(repo_root)}")

    if not removed_any:
        print("No generated packaging paths found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
