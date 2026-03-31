# Installation

## Dependencies

ProofOfThought requires Python 3.13.

### Core Dependencies

For development, create and activate the project virtual environment first:

```bash
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## Z3 Verification Setup

### JSON Backend

The JSON backend requires no additional setup beyond installing `z3-solver`, which includes the Python API.

### SMT2 Backend

The SMT2 backend requires the `z3` binary to be available in your active environment:

```bash
z3 --version
```

If you installed dependencies into the repo's `venv`, activate it before running examples or tests so `venv/bin/z3` is on `PATH`:

```bash
source venv/bin/activate
z3 --version
```

You can also specify the binary path explicitly in code:
```python
ProofOfThought(..., z3_path="/path/to/z3")
```

## API Keys

### OpenAI

For OpenAI access, create a `.env` file with:

```bash
OPENAI_API_KEY=sk-...
```

### Azure OpenAI

For Azure OpenAI deployments, configure these variables in `.env`:
```bash
AZURE_OPENAI_KEY=...
AZURE_OPENAI_ENDPOINT=https://....openai.azure.com/
AZURE_API_VERSION=2024-12-01-preview
AZURE_DEPLOYMENT_NAME=gpt-5
```

Then use it in your code:

```python
from utils.azure_config import get_client_config

config = get_client_config()  # Returns {"llm_client": AzureOpenAI(...), "model": str}
pot = ProofOfThought(llm_client=config["llm_client"], model=config["model"])
```

## Verification

To verify your installation is working correctly:

```bash
python examples/simple_usage.py
```

You should see output similar to:

```
Question: Would Nancy Pelosi publicly denounce abortion?
Answer: False
Success: True
Attempts: 1
```

## Troubleshooting

Common issues and their solutions:

### Z3 CLI not found (SMT2 backend)

**Error:**
```
FileNotFoundError: Z3 executable not found: 'z3'
```

**Solutions:**

1. Switch to JSON backend: `ProofOfThought(backend="json")`
2. Specify the Z3 path explicitly: `ProofOfThought(z3_path="/path/to/z3")`
3. Add Z3 to your PATH: `export PATH=$PATH:/path/to/z3/bin`

### Import errors when running examples

**Incorrect approach:**
```bash
cd examples
python simple_usage.py  # ❌ ModuleNotFoundError
```

**Correct approach:**

```bash
cd /path/to/proofofthought
python examples/simple_usage.py  # ✓
```

**Reason:** The example scripts rely on the project root and the activated virtual environment so both `z3adapter` and `z3` resolve correctly.

### Azure authentication errors

First, verify that all `.env` variables are properly set and that your endpoint URL is correct. You can test the configuration with:
```python
from utils.azure_config import get_client_config
config = get_client_config()  # Should not raise
```

## Version Constraints

The following version constraints are defined in `pyproject.toml` and `requirements.txt`:

- **Python:** `>=3.13,<3.14`
- **Z3:** `>=4.15.0` (tested with `4.15.3.0`)
- **OpenAI:** `>=2.0.0` (tested with `2.0.1`)
- **scikit-learn:** `>=1.7.0` (tested with `1.7.2`)
- **NumPy:** `>=2.3.0` (tested with `2.3.3`)
