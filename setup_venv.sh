#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

if [[ ! -f "pyproject.toml" ]] && [[ ! -f "requirements.txt" ]]; then
  echo "Error: Please run this script from the project root containing pyproject.toml or requirements.txt." >&2
  exit 1
fi

PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Error: '$PYTHON_BIN' not found. Install Python 3 and try again." >&2
  exit 1
fi

VENV_DIR="${VENV_DIR:-$PROJECT_ROOT/.venv}"

if [[ -d "$VENV_DIR" ]]; then
  echo "Virtual environment already exists at $VENV_DIR"
else
  echo "Creating virtual environment at $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

if [[ -f "requirements.txt" ]]; then
  echo "Installing dependencies from requirements.txt"
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
elif [[ -f "pyproject.toml" ]]; then
  echo "Installing project with pip"
  pip install --upgrade pip >/dev/null
  pip install -e .
fi

echo
read -r -p "Have you added your LLM API keys to the .env file? Press Enter to confirm. "

echo "Setup complete. Activate the environment with 'source $VENV_DIR/bin/activate'."
