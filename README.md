# ProofOfThought

LLM-based reasoning using Z3 theorem proving.

## Quick Start

```python
from openai import OpenAI
from z3adapter.reasoning import ProofOfThought

client = OpenAI(api_key="...")
pot = ProofOfThought(llm_client=client)

result = pot.query("Would Nancy Pelosi publicly denounce abortion?")
print(result.answer)  # False
```

## Batch Evaluation

```python
from z3adapter.reasoning import EvaluationPipeline

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

1. **High-level API** (`z3adapter.reasoning`) - Simple Python interface for reasoning tasks
2. **Low-level execution** (`z3adapter.backends`) - JSON DSL or SMT2 backend for Z3

Most users should use the high-level API.

## Examples

See `examples/` directory for complete examples including Azure OpenAI support.

## Running Experiments

To run all benchmarks with both backends and generate results:

```bash
python experiments_pipeline.py
```

This will:
- Run all 5 benchmarks (ProntoQA, FOLIO, ProofWriter, ConditionalQA, StrategyQA)
- Test both SMT2 and JSON backends
- Generate results tables in `results/`
- Automatically update the benchmark results section below

<!-- BENCHMARK_RESULTS_START -->

# Benchmark Results

**Last Updated:** 2025-10-16 18:14:07

| Benchmark | Backend | Samples | Accuracy | Precision | Recall | F1 Score | Success Rate |
|-----------|---------|---------|----------|-----------|--------|----------|--------------|
| PRONTOQA | SMT2 | 100 | 100.00% | 1.0000 | 1.0000 | 1.0000 | 100.00% |
| FOLIO | SMT2 | 100 | 69.00% | 0.6949 | 0.7736 | 0.7321 | 99.00% |
| PROOFWRITER | SMT2 | 96 | 98.96% | 1.0000 | 1.0000 | 1.0000 | 98.96% |
| CONDITIONALQA | SMT2 | 100 | 83.00% | 0.9375 | 0.8219 | 0.8759 | 100.00% |
| STRATEGYQA | SMT2 | 100 | 84.00% | 0.8205 | 0.7805 | 0.8000 | 100.00% |
| PRONTOQA | JSON | 100 | 99.00% | 1.0000 | 0.9815 | 0.9907 | 100.00% |
| FOLIO | JSON | 100 | 76.00% | 0.7619 | 0.9412 | 0.8421 | 94.00% |
| PROOFWRITER | JSON | 96 | 95.83% | 1.0000 | 1.0000 | 1.0000 | 95.83% |
| CONDITIONALQA | JSON | 100 | 76.00% | 0.9180 | 0.8750 | 0.8960 | 89.00% |
| STRATEGYQA | JSON | 100 | 68.00% | 0.7500 | 0.7895 | 0.7692 | 86.00% |

## Notes

- **Accuracy**: Percentage of correct predictions
- **Precision**: True positives / (True positives + False positives)
- **Recall**: True positives / (True positives + False negatives)
- **F1 Score**: Harmonic mean of precision and recall
- **Success Rate**: Percentage of queries that completed without errors


<!-- BENCHMARK_RESULTS_END -->
