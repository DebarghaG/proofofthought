# Installation

## Dependencies

ProofOfThought requires Python 3.12 or higher (as specified in `pyproject.toml`).

### Core Dependencies

Install the core dependencies using:

```bash
pip install -r requirements.txt
```

## Z3 Verification Setup

### JSON Backend

The JSON backend requires no additional setup beyond installing `z3-solver`, which includes the Python API.

### SMT2 Backend

The SMT2 backend requires the Z3 CLI to be available in your PATH:

```bash
z3 --version
```

If Z3 is not found, note that the `z3-solver` package includes a CLI binary in `site-packages`. You can locate it with:

```bash
python -c "import z3; print(z3.__file__)"
# The CLI is typically located at: .../site-packages/z3/bin/z3
```

On macOS/Linux, you can either add it to your PATH or specify the path in your code:
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
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://....openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_GPT5_DEPLOYMENT_NAME=gpt-5
AZURE_GPT4O_DEPLOYMENT_NAME=gpt-4o
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

**Reason:** The example scripts use `sys.path.insert(0, str(Path(__file__).parent.parent))` to locate the `z3adapter` and `utils` modules from the project root.

### Azure authentication errors

First, verify that all `.env` variables are properly set and that your endpoint URL is correct. You can test the configuration with:
```python
from utils.azure_config import get_client_config
config = get_client_config()  # Should not raise
```

## Version Constraints

The following version constraints are defined in `pyproject.toml` and `requirements.txt`:

- **Python:** `>=3.12`
- **Z3:** `>=4.15.0` (tested with `4.15.3.0`)
- **OpenAI:** `>=2.0.0` (tested with `2.0.1`)
- **scikit-learn:** `>=1.7.0` (tested with `1.7.2`)
- **NumPy:** `>=2.3.0` (tested with `2.3.3`)
