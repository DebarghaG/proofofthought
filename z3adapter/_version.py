"""Version helpers for the packaged release."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re


def _read_version_file() -> str:
    """Read the packaged version file."""
    return Path(__file__).with_name("VERSION").read_text().strip()


BASE_VERSION = _read_version_file()
__version__ = BASE_VERSION

_NIGHTLY_STAMP_RE = re.compile(r"^\d{12}$")


def stable_base_version(version: str | None = None) -> str:
    """Return the stable base portion of a version string."""
    candidate = version or BASE_VERSION
    return candidate.split(".dev", maxsplit=1)[0]


def build_nightly_version(stamp: str) -> str:
    """Build a PyPI-compatible nightly version from a UTC timestamp stamp."""
    if not _NIGHTLY_STAMP_RE.fullmatch(stamp):
        raise ValueError("Nightly stamp must use UTC format YYYYMMDDHHMM")
    return f"{stable_base_version()}.dev{stamp}"


def utc_nightly_stamp(now: datetime | None = None) -> str:
    """Return a UTC timestamp stamp suitable for nightly dev releases."""
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Nightly timestamp must be timezone-aware")
    return now.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
