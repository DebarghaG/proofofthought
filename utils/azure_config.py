"""
Azure OpenAI Configuration Helper

This module provides easy configuration for Azure OpenAI GPT-5,
with support for environment variables and multiple deployment options.

To use this module:
1. Copy .env.example to .env in the project root
2. Fill in your Azure OpenAI credentials in .env
3. Import and use get_azure_client() or get_client_config()
"""

import os
from pathlib import Path
from typing import Any

from openai import AzureOpenAI

# Load environment variables from .env file
try:
    from dotenv import load_dotenv

    # Load from project root .env file
    project_root = Path(__file__).parent.parent
    env_path = project_root / ".env"
    load_dotenv(dotenv_path=env_path)
except ImportError:
    print("Warning: python-dotenv not installed. Install with: pip install python-dotenv")
    print("Falling back to system environment variables only.")

# Azure OpenAI GPT-5 Configuration
# These are loaded from environment variables only (no hardcoded defaults)
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_API_KEY = os.getenv("AZURE_OPENAI_KEY")
DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-5")
API_VERSION = os.getenv("AZURE_API_VERSION", "2024-12-01-preview")

# GPT-5 specific settings
GPT5_MAX_TOKENS = 16384
GPT5_TEMPERATURE = 0.1


def get_azure_client() -> AzureOpenAI:
    """Get configured Azure OpenAI client for GPT-5.

    Returns:
        Configured AzureOpenAI client

    Environment Variables (required):
        AZURE_OPENAI_ENDPOINT: Azure endpoint URL
        AZURE_OPENAI_KEY: API key
        AZURE_DEPLOYMENT_NAME: Deployment name (default: gpt-5)
        AZURE_API_VERSION: API version (default: 2024-12-01-preview)

    Raises:
        ValueError: If required environment variables are not set
    """
    if not AZURE_ENDPOINT:
        raise ValueError(
            "AZURE_OPENAI_ENDPOINT is not set. "
            "Please set it in your .env file or environment variables."
        )
    if not AZURE_API_KEY:
        raise ValueError(
            "AZURE_OPENAI_KEY is not set. "
            "Please set it in your .env file or environment variables."
        )

    return AzureOpenAI(
        api_version=API_VERSION,
        azure_endpoint=AZURE_ENDPOINT,
        api_key=AZURE_API_KEY,
    )


def get_client_config() -> dict[str, Any]:
    """Get client configuration dictionary.

    Returns:
        Dictionary with client, model, and recommended settings
    """
    return {
        "llm_client": get_azure_client(),
        "model": DEPLOYMENT_NAME,
        "max_tokens": GPT5_MAX_TOKENS,
        "temperature": GPT5_TEMPERATURE,
    }


# Example usage:
if __name__ == "__main__":
    # Test configuration
    print("Azure OpenAI GPT-5 Configuration:")
    print(f"  Endpoint: {AZURE_ENDPOINT}")
    print(f"  Deployment: {DEPLOYMENT_NAME}")
    print(f"  API Version: {API_VERSION}")
    print(f"  Max Tokens: {GPT5_MAX_TOKENS}")
    print(f"  Temperature: {GPT5_TEMPERATURE}")

    # Test client creation
    client = get_azure_client()
    print("\n✓ Azure OpenAI client created successfully")

    # Show config dict
    config = get_client_config()
    print(f"\nClient config keys: {list(config.keys())}")
