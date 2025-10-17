# Installation

## Dependencies

Python 3.12+ required (`pyproject.toml` specifies `requires-python = ">=3.12"`).

### Core

```bash
pip install -r requirements.txt
```

Installs:

- `z3-solver>=4.15.0` - Z3 Python API (JSONBackend) + CLI binary (SMT2Backend)
- `openai>=2.0.0` - LLM client (supports Azure OpenAI via same interface)
- `scikit-learn>=1.7.0` - Evaluation metrics (`confusion_matrix`, `accuracy_score`, etc.)
- `numpy>=2.3.0` - Numerical operations
- `python-dotenv>=1.1.0` - Environment variable management

### Development (Optional)

```bash
pip install -e ".[dev]"
```

Additional tools:

- `black>=25.9.0` - Code formatter
- `ruff>=0.13.0` - Linter
- `mypy>=1.18.0` - Type checker
- `pytest>=8.0.0` - Test runner
- `pre-commit>=4.3.0` - Git hooks

## Z3 Verification

### JSON Backend

No additional setup. `z3-solver` package includes Python API.

### SMT2 Backend

Requires Z3 CLI in PATH:

```bash
z3 --version
```

If missing, `z3-solver` package includes CLI in `site-packages`. Locate via:

```bash
python -c "import z3; print(z3.__file__)"
# CLI typically at: .../site-packages/z3/bin/z3
```

macOS/Linux: Add to PATH or specify in code:
```python
ProofOfThought(..., z3_path="/path/to/z3")
```

## API Keys

### OpenAI

`.env`:
```bash
OPENAI_API_KEY=sk-...
```

### Azure OpenAI

`.env`:
```bash
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://....openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_GPT5_DEPLOYMENT_NAME=gpt-5
AZURE_GPT4O_DEPLOYMENT_NAME=gpt-4o
```

Usage:
```python
from utils.azure_config import get_client_config

config = get_client_config()  # Returns {"llm_client": AzureOpenAI(...), "model": str}
pot = ProofOfThought(llm_client=config["llm_client"], model=config["model"])
```

## Verification

```bash
python examples/simple_usage.py
```

Expected output structure:
```
Question: Would Nancy Pelosi publicly denounce abortion?
Answer: False
Success: True
Attempts: 1
```

## Troubleshooting

**Z3 CLI not found (SMT2 backend)**

Error:
```
FileNotFoundError: Z3 executable not found: 'z3'
```

Solutions:
1. Use JSON backend: `ProofOfThought(backend="json")`
2. Specify Z3 path: `ProofOfThought(z3_path="/path/to/z3")`
3. Add to PATH: `export PATH=$PATH:/path/to/z3/bin`

**Import errors when running examples**

Wrong:
```bash
cd examples
python simple_usage.py  # ❌ ModuleNotFoundError
```

Correct:
```bash
cd /path/to/proofofthought
python examples/simple_usage.py  # ✓
```

Reason: `examples/*.py` use `sys.path.insert(0, str(Path(__file__).parent.parent))` to find `z3adapter` and `utils` modules from project root.

**Azure authentication errors**

Verify `.env` variables are set and endpoint URL is correct. Test via:
```python
from utils.azure_config import get_client_config
config = get_client_config()  # Should not raise
```

## Version Constraints

From `pyproject.toml` and `requirements.txt`:

- Python: `>=3.12`
- Z3: `>=4.15.0` (tested with `4.15.3.0`)
- OpenAI: `>=2.0.0` (tested with `2.0.1`)
- scikit-learn: `>=1.7.0` (tested with `1.7.2`)
- NumPy: `>=2.3.0` (tested with `2.3.3`)
