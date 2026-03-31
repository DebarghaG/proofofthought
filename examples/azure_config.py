"""Example-local Azure configuration helpers."""

# ruff: noqa: E402

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.azure_config import DEPLOYMENT_NAME, get_azure_client, get_client_config

__all__ = ["DEPLOYMENT_NAME", "get_azure_client", "get_client_config"]
