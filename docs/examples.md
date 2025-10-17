# Examples

All examples are in the `examples/` directory. Run them from the project root:

```bash
cd /path/to/proofofthought
python examples/simple_usage.py
```

## Basic Usage

### Single query

```python
from openai import OpenAI
from z3adapter.reasoning import ProofOfThought

# Set up client
client = OpenAI(api_key="...")
pot = ProofOfThought(llm_client=client, model="gpt-4o")

# Ask a question
result = pot.query("Would Nancy Pelosi publicly denounce abortion?")

# Check the answer
print(result.answer)  # False
print(f"Successful: {result.success}")
print(f"Attempts: {result.num_attempts}")
```

File: `examples/simple_usage.py`

### Azure OpenAI

```python
from utils.azure_config import get_client_config
from z3adapter.reasoning import ProofOfThought

# Get Azure config from environment
config = get_client_config()

# Initialize with Azure client
pot = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"]
)

# Use normally
result = pot.query("Can fish breathe underwater?")
print(result.answer)  # True
```

File: `examples/azure_simple_example.py`

Required `.env` variables:

```bash
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://....openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_GPT5_DEPLOYMENT_NAME=gpt-5
```

## Backend Comparison

### Test both backends

```python
from utils.azure_config import get_client_config
from z3adapter.reasoning import ProofOfThought

config = get_client_config()
question = "Can fish breathe underwater?"

# JSON backend
pot_json = ProofOfThought(
    llm_client=config["llm_client"],
    backend="json"
)
result_json = pot_json.query(question)

# SMT2 backend
pot_smt2 = ProofOfThought(
    llm_client=config["llm_client"],
    backend="smt2"
)
result_smt2 = pot_smt2.query(question)

print(f"JSON backend: {result_json.answer}")
print(f"SMT2 backend: {result_smt2.answer}")
```

File: `examples/backend_comparison.py`

## Batch Evaluation

### Evaluate on a dataset

```python
from z3adapter.reasoning import ProofOfThought, EvaluationPipeline

# Set up evaluator
pot = ProofOfThought(llm_client=client)
evaluator = EvaluationPipeline(
    proof_of_thought=pot,
    output_dir="results/"
)

# Run evaluation
result = evaluator.evaluate(
    dataset="data/strategyQA_train.json",
    question_field="question",
    answer_field="answer",
    max_samples=100
)

# Print metrics
print(f"Accuracy: {result.metrics.accuracy:.2%}")
print(f"Precision: {result.metrics.precision:.4f}")
print(f"Recall: {result.metrics.recall:.4f}")
print(f"F1 Score: {result.metrics.f1:.4f}")
print(f"Success Rate: {result.metrics.success_rate:.2%}")
```

File: `examples/batch_evaluation.py`

### With Azure and SMT2 backend

```python
from utils.azure_config import get_client_config
from z3adapter.reasoning import ProofOfThought, EvaluationPipeline

config = get_client_config()

pot = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="smt2"
)

evaluator = EvaluationPipeline(proof_of_thought=pot)
result = evaluator.evaluate(
    dataset="data/strategyQA_train.json",
    max_samples=50
)

print(f"Accuracy: {result.metrics.accuracy:.2%}")
```

File: `examples/batch_evaluation_smt2_azure.py`

## Running Experiments

### Full benchmark suite

Run all 5 benchmarks with both backends:

```bash
python experiments_pipeline.py
```

This evaluates:

- ProntoQA (100 samples)
- FOLIO (100 samples)
- ProofWriter (96 samples)
- ConditionalQA (100 samples)
- StrategyQA (100 samples)

Results are saved to `results/` and the README is auto-updated.

File: `experiments_pipeline.py`

## Advanced Usage

### Save generated programs

```python
result = pot.query(
    "Can fish breathe underwater?",
    save_program=True
)

# Programs saved to cache_dir with .json or .smt2 extension
print(f"Program saved: {result.json_program}")
```

### Custom timeouts

```python
pot = ProofOfThought(
    llm_client=client,
    verify_timeout=5000,      # 5 seconds
    optimize_timeout=50000,   # 50 seconds
    max_attempts=5
)
```

### Custom Z3 path

```python
pot = ProofOfThought(
    llm_client=client,
    backend="smt2",
    z3_path="/usr/local/bin/z3"
)
```

### Override max attempts per query

```python
# Default max_attempts=3
pot = ProofOfThought(llm_client=client)

# Override for specific query
result = pot.query(
    "Complex question...",
    max_attempts=10
)
```

## Dataset Format

Evaluation expects JSON with question/answer fields:

```json
[
  {
    "question": "Can fish breathe underwater?",
    "answer": true
  },
  {
    "question": "Do humans have wings?",
    "answer": false
  }
]
```

Custom field names:

```python
result = evaluator.evaluate(
    dataset="custom_dataset.json",
    question_field="query",
    answer_field="label",
    max_samples=100
)
```

## Testing Strategy

Want to test on a specific dataset? See `examples/test_strategyqa.py`:

```python
from utils.azure_config import get_client_config
from z3adapter.reasoning import ProofOfThought, EvaluationPipeline

config = get_client_config()

# JSON backend
pot_json = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="json"
)

evaluator = EvaluationPipeline(proof_of_thought=pot_json)
result = evaluator.evaluate(
    dataset="data/strategyQA_train.json",
    max_samples=100
)

print(f"StrategyQA JSON Backend Accuracy: {result.metrics.accuracy:.2%}")
```

## Troubleshooting

**Examples fail with import errors?**

Make sure you're running from the project root, not from `examples/`:

```bash
# Wrong
cd examples
python simple_usage.py  # ❌ Import error

# Right
cd /path/to/proofofthought
python examples/simple_usage.py  # ✓ Works
```

**Azure config not found?**

Check your `.env` file has all required Azure variables. See [Installation](installation.md).

**Z3 not found?**

Either install Z3 CLI or use JSON backend:

```python
pot = ProofOfThought(llm_client=client, backend="json")
```
