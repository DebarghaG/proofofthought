# ProofOfThought

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Z3](https://img.shields.io/badge/Z3-4.15+-green.svg)](https://github.com/Z3Prover/z3)
[![OpenAI](https://img.shields.io/badge/OpenAI-Compatible-412991.svg)](https://platform.openai.com/)
[![Azure](https://img.shields.io/badge/Azure-GPT--4o/GPT--5-0078D4.svg)](https://azure.microsoft.com/en-us/products/ai-services/openai-service)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

LLM-based reasoning using Z3 theorem proving with multiple backend support (SMT2 and JSON).

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
from z3adapter.reasoning import EvaluationPipeline, ProofOfThought

evaluator = EvaluationPipeline(proof_of_thought=pot, output_dir="results/")
result = evaluator.evaluate(
    dataset="data/strategyQA_train.json",
    question_field="question",
    answer_field="answer",
    max_samples=10
)
print(f"Accuracy: {result.metrics.accuracy:.2%}")
```

## Installation

```bash
pip install -r requirements.txt
```

## Features

- **Dual Backend Support**: Choose between SMT2 (default) or JSON execution backends
- **Azure OpenAI Integration**: Native support for Azure GPT-4o and GPT-5 models
- **Comprehensive Benchmarks**: Evaluated on 5 reasoning datasets (ProntoQA, FOLIO, ProofWriter, ConditionalQA, StrategyQA)
- **High-level API**: Simple Python interface for reasoning tasks
- **Batch Evaluation Pipeline**: Built-in tools for dataset evaluation and metrics
- **Postprocessing Techniques**: Self-Refine, Self-Consistency, Decomposed Prompting, and Least-to-Most Prompting for enhanced reasoning quality

## Backend Selection

ProofOfThought supports two execution backends:

```python
# SMT2 backend (default) - Standard SMT-LIB 2.0 via Z3 CLI
pot = ProofOfThought(llm_client=client, backend="smt2")

# JSON backend - Custom DSL via Python Z3 API
pot = ProofOfThought(llm_client=client, backend="json")
```

See [BACKENDS.md](BACKENDS.md) for details on choosing a backend.

## Postprocessing Techniques

Enhance reasoning quality with advanced postprocessing techniques:

```python
# Enable Self-Refine for iterative refinement
pot = ProofOfThought(
    llm_client=client,
    postprocessors=["self_refine"],
    postprocessor_configs={"self_refine": {"num_iterations": 2}}
)

# Use Self-Consistency for improved reliability via majority voting
pot = ProofOfThought(
    llm_client=client,
    postprocessors=["self_consistency"],
    postprocessor_configs={"self_consistency": {"num_samples": 5}}
)

# Chain multiple postprocessors
pot = ProofOfThought(
    llm_client=client,
    postprocessors=["self_refine", "self_consistency"]
)
```

Available techniques:
- **Self-Refine**: Iterative refinement through self-critique
- **Self-Consistency**: Majority voting across multiple reasoning paths
- **Decomposed Prompting**: Breaking complex questions into sub-questions
- **Least-to-Most Prompting**: Progressive problem solving from simple to complex

See [POSTPROCESSORS.md](POSTPROCESSORS.md) for complete documentation and usage examples.

## Architecture

The system has two layers:

1. **High-level API** (`z3adapter.reasoning`) - Simple Python interface for reasoning tasks
2. **Low-level execution** (`z3adapter.backends`) - JSON DSL or SMT2 backend for Z3

Most users should use the high-level API.

## Examples

See `examples/` directory for complete examples including Azure OpenAI support.

**Note:** Examples should be run from the project root directory:

```bash
cd /path/to/proofofthought
python examples/simple_usage.py
```

For Azure examples that use `azure_config`, the helper module is located at `utils/azure_config.py`. When running from the project root with `PYTHONPATH` set correctly, examples can import it directly:

```python
from utils.azure_config import get_client_config
```

## Running Experiments

You can use this repository as a strong baseline for LLM+Solver methods. This code is generally benchmarked with GPT-5 on the first 100 samples of 5 datasets, as an indicator of whether we broke something during development. These numbers are not the best, and you can certainly get better numbers with better prompt engineering with this same tooling. Please feel free to put in a PR if you get better numbers with modified prompts.

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



<!-- BENCHMARK_RESULTS_END -->

# Citations

Please consider citing our work if you find this useful.

```
@inproceedings{
ganguly2024proof,
title={{PROOF} {OF} {THOUGHT} : Neurosymbolic Program Synthesis allows Robust and Interpretable Reasoning},
author={Debargha Ganguly and Srinivasan Iyengar and Vipin Chaudhary and Shivkumar Kalyanaraman},
booktitle={The First Workshop on System-2 Reasoning at Scale, NeurIPS'24},
year={2024},
url={https://openreview.net/forum?id=Pxx3r14j3U}
}
```

```
@inproceedings{
ganguly2025grammars,
title={Grammars of Formal Uncertainty: When to Trust {LLM}s in Automated Reasoning Tasks},
author={Debargha Ganguly and Vikash Singh and Sreehari Sankar and Biyao Zhang and Xuecen Zhang and Srinivasan Iyengar and Xiaotian Han and Amit Sharma and Shivkumar Kalyanaraman and Vipin Chaudhary},
booktitle={The Thirty-ninth Annual Conference on Neural Information Processing Systems},
year={2025},
url={https://openreview.net/forum?id=QfKpJ00t2L}
}
```