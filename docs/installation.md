# Installation

## Requirements

- Python 3.12+
- Z3 theorem prover
- OpenAI-compatible LLM API

## Install Python dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `z3-solver` - Z3 Python bindings
- `openai` - LLM client
- `scikit-learn`, `numpy` - For evaluation metrics
- `python-dotenv` - Environment variable management

## Install Z3 CLI (for SMT2 backend)

The SMT2 backend needs the Z3 command-line tool.

### macOS
```bash
brew install z3
```

### Ubuntu/Debian
```bash
sudo apt-get install z3
```

### From source
```bash
git clone https://github.com/Z3Prover/z3.git
cd z3
python scripts/mk_make.py
cd build
make
sudo make install
```

### Verify installation
```bash
z3 --version
```

**Note:** The JSON backend doesn't need the CLI—it uses Z3's Python API.

## Set up API keys

### OpenAI

Create a `.env` file in the project root:

```bash
OPENAI_API_KEY=sk-...
```

### Azure OpenAI

For Azure GPT-4o or GPT-5, add these to `.env`:

```bash
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://....openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_GPT5_DEPLOYMENT_NAME=gpt-5
AZURE_GPT4O_DEPLOYMENT_NAME=gpt-4o
```

See `examples/azure_simple_example.py` for Azure usage.

## Verify setup

Run a quick test:

```bash
python examples/simple_usage.py
```

You should see output like:

```
Question: Would Nancy Pelosi publicly denounce abortion?
Answer: False
Success: True
```

## Development setup

For contributors:

```bash
pip install -e ".[dev]"
pre-commit install
```

This installs development tools:
- `black` - Code formatter
- `ruff` - Linter
- `mypy` - Type checker
- `pytest` - Test runner
- `pre-commit` - Git hooks

## Troubleshooting

**Z3 not found?**

If you get `z3: command not found`, either:
1. Install the Z3 CLI (see above)
2. Use the JSON backend instead: `ProofOfThought(backend="json")`

**API key errors?**

Make sure your `.env` file is in the project root and contains valid keys.

**Import errors?**

Run examples from the project root:

```bash
cd /path/to/proofofthought
python examples/simple_usage.py
```

Not from the `examples/` directory.
