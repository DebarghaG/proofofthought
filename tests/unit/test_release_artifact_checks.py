"""Tests for release artifact safety checks."""

from __future__ import annotations

import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT_PATH = Path("scripts/check_release_artifacts.py")


class TestReleaseArtifactChecks(unittest.TestCase):
    """Verify artifact scanning catches obvious secret leakage."""

    def test_placeholder_docs_are_allowed(self) -> None:
        """README placeholders should not be treated as secrets."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact = Path(tmp_dir) / "proofofthought-1.0.1-py3-none-any.whl"
            with zipfile.ZipFile(artifact, "w") as archive:
                archive.writestr(
                    "proofofthought-1.0.1.dist-info/METADATA",
                    "OPENAI_API_KEY=your-api-key-here\nAZURE_OPENAI_KEY=your-azure-key-here\n",
                )
            result = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), str(artifact)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_secret_file_in_artifact_is_rejected(self) -> None:
        """Artifacts should fail if they contain blocked secret files."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact = Path(tmp_dir) / "proofofthought-1.0.1.tar.gz"
            with tarfile.open(artifact, "w:gz") as archive:
                secret_file = Path(tmp_dir) / ".env"
                secret_file.write_text("OPENAI_API_KEY=sk-real-secret-value\n")
                archive.add(secret_file, arcname="proofofthought-1.0.1/.env")
            result = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), str(artifact)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("blocked file path", result.stderr)

    def test_removed_runtime_module_in_artifact_is_rejected(self) -> None:
        """Artifacts should fail if a deleted JSON-era module leaks into the build."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifact = Path(tmp_dir) / "proofofthought-2.0.0-py3-none-any.whl"
            with zipfile.ZipFile(artifact, "w") as archive:
                archive.writestr("z3adapter/backends/json_backend.py", "# stale module")
            result = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), str(artifact)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("removed runtime module present in artifact", result.stderr)


if __name__ == "__main__":
    unittest.main()
