# ProofOfThought

LLM-based reasoning using Z3 theorem proving.

## Quick Start

```python
from openai import OpenAI
from z3dsl.reasoning import ProofOfThought

client = OpenAI(api_key="...")
pot = ProofOfThought(llm_client=client)

result = pot.query("Would Nancy Pelosi publicly denounce abortion?")
print(result.answer)  # False
```

## Batch Evaluation

```python
from z3dsl.reasoning import EvaluationPipeline

evaluator = EvaluationPipeline(pot, output_dir="results/")
result = evaluator.evaluate(
    dataset="strategyqa_train.json",
    max_samples=10
)
print(f"Accuracy: {result.metrics.accuracy:.2%}")
```

## Installation

```bash
pip install z3-solver openai scikit-learn numpy
```

## Backend Selection

ProofOfThought supports two execution backends:

```python
# SMT2 backend (default) - Standard SMT-LIB 2.0 via Z3 CLI
pot = ProofOfThought(llm_client=client, backend="smt2")

# JSON backend - Custom DSL via Python Z3 API
pot = ProofOfThought(llm_client=client, backend="json")
```

See [BACKENDS.md](BACKENDS.md) for details on choosing a backend.

## Architecture

The system has two layers:

1. **High-level API** (`z3dsl.reasoning`) - Simple Python interface for reasoning tasks
2. **Low-level execution** (`z3dsl.backends`) - JSON DSL or SMT2 backend for Z3

Most users should use the high-level API.

## Examples

See `examples/` directory for complete examples including Azure OpenAI support.
