# ProofOfThought

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Z3](https://img.shields.io/badge/Z3-4.15+-green.svg)](https://github.com/Z3Prover/z3)
[![OpenAI](https://img.shields.io/badge/OpenAI-Compatible-412991.svg)](https://platform.openai.com/)
[![Azure](https://img.shields.io/badge/Azure-GPT--4o/GPT--5-0078D4.svg)](https://azure.microsoft.com/en-us/products/ai-services/openai-service)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

LLM-based reasoning using Z3 theorem proving — now built around an **agentic SMT-LIB scratchpad** (with the classic SMT2 and JSON single-shot backends preserved).

## The agentic paradigm (v2.0)

**Going forward, ProofOfThought is moving to an agentic paradigm**: instead of generating one program and hoping it runs, the model iteratively interacts with an SMT-LIB scratchpad — it calls a `z3_solve` tool, reads Z3's verdict (`sat` / `unsat` / errors), repairs or strengthens its encoding, and terminates with an explicit `finish` tool call. Canonically the answer is established by **proof by contradiction**: assert the negation of the candidate, and a clean UNSAT proves it. Every answer carries a `proof_status` (`proof_by_contradiction` / `sat_witness` / `unverified`) and the machine-checkable trajectory of SMT programs and Z3 verdicts that backs it — a premature `finish` with no decisive verdict is rejected, so `verified=True` is never just the model's say-so. Saved trajectory programs can be independently re-checked with `AgenticBackend.reverify()`.

This loop was developed and battle-tested in our SMT evaluation harness across tens of thousands of agent trajectories, and it is the default backend as of v2.0.0. The previous single-shot backends remain fully supported. See [docs/agentic.md](docs/agentic.md).

## Features

- **Agentic SMT-LIB Scratchpad (new default)**: Iterative `z3_solve` ⇄ `finish` tool loop with verdict-aware nudges, in-process Z3 (no CLI binary needed), and robust textual tool-call recovery for vLLM/sglang-served models
- **Triple Backend Support**: `agentic` (default), `smt2`, or `json` execution backends
- **Azure OpenAI Integration**: Native support for Azure GPT-4o and GPT-5 models
- **Comprehensive Benchmarks**: Evaluated on 5 reasoning datasets (ProntoQA, FOLIO, ProofWriter, ConditionalQA, StrategyQA)
- **High-level API**: Simple Python interface for reasoning tasks
- **Batch Evaluation Pipeline**: Built-in tools for dataset evaluation and metrics
- **Postprocessing Techniques**: Self-Refine, Self-Consistency, Decomposed Prompting, and Least-to-Most Prompting for enhanced reasoning quality (single-shot backends)

## Installation

### From PyPI (Recommended)

Install the latest stable version:

```bash
pip install proofofthought
```

**Note:** Package name is `proofofthought`, but imports use `z3adapter`:
```python
from z3adapter.reasoning import ProofOfThought
```

### From Source (Development)

For contributing or using the latest development version:

```bash
git clone https://github.com/debarghaG/proofofthought.git
cd proofofthought
pip install -r requirements.txt
```

### Prerequisites

- Python 3.12 or higher
- An OpenAI API key or Azure OpenAI endpoint
- Z3 solver (automatically installed via `z3-solver` package)

## Setup

### Environment Variables

Create a `.env` file in your project directory:

**For OpenAI:**
```bash
OPENAI_API_KEY=your-api-key-here
```

**For Azure OpenAI:**
```bash
AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com/
AZURE_OPENAI_KEY=your-azure-key-here
AZURE_DEPLOYMENT_NAME=gpt-5  # or gpt-4o
AZURE_API_VERSION=2024-02-15-preview
```

You can also set these as system environment variables instead of using a `.env` file.

## Quick Start

### Using OpenAI

```python
import os
from dotenv import load_dotenv
from openai import OpenAI
from z3adapter.reasoning import ProofOfThought

# Load environment variables
load_dotenv()

# Create OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Initialize ProofOfThought (agentic SMT-LIB scratchpad by default)
pot = ProofOfThought(llm_client=client, model="gpt-4o")

# Ask a question
result = pot.query("Would Nancy Pelosi publicly denounce abortion?")
print(result.answer_text)   # "No" — canonical answer (any shape: Yes/No, MCQ letter, value)
print(result.answer)        # False — boolean view; None for non-boolean answers
print(result.proof_status)  # "proof_by_contradiction" — how the trajectory backs it
print(result.iterations)    # tool-loop turns the agent needed
for step in result.smt_history or []:
    print(step["z3_output"]["sat_result"])  # the full SMT scratchpad trajectory
```

Local OpenAI-compatible endpoints (vLLM, sglang, ...) work the same way:

```python
client = OpenAI(base_url="http://localhost:8000/v1", api_key="none")
pot = ProofOfThought(llm_client=client, model="Qwen/Qwen3.5-9B")
```

### Using Azure OpenAI

```python
import os
from dotenv import load_dotenv
from openai import AzureOpenAI
from z3adapter.reasoning import ProofOfThought

# Load environment variables
load_dotenv()

# Create Azure OpenAI client
client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version=os.getenv("AZURE_API_VERSION")
)

# Initialize ProofOfThought with your deployment name
pot = ProofOfThought(
    llm_client=client,
    model=os.getenv("AZURE_DEPLOYMENT_NAME")  # e.g., "gpt-4o" or "gpt-5"
)

# Ask a question
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

## Backend Selection

ProofOfThought supports three execution backends:

```python
# Agentic backend (default) - iterative SMT-LIB scratchpad via tool calls
pot = ProofOfThought(llm_client=client, backend="agentic")

# SMT2 backend - single-shot SMT-LIB 2.0 via Z3 CLI (pre-2.0 default)
pot = ProofOfThought(llm_client=client, backend="smt2")

# JSON backend - single-shot custom DSL via Python Z3 API
pot = ProofOfThought(llm_client=client, backend="json")
```

See [docs/agentic.md](docs/agentic.md) and [docs/backends.md](docs/backends.md) for details on choosing a backend.

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

Postprocessors apply to the single-shot backends (`smt2`/`json`) only — configuring them with the agentic backend raises `ValueError` at construction. Pass `backend="smt2"` when using them.

Available techniques:
- **Self-Refine**: Iterative refinement through self-critique
- **Self-Consistency**: Majority voting across multiple reasoning paths
- **Decomposed Prompting**: Breaking complex questions into sub-questions
- **Least-to-Most Prompting**: Progressive problem solving from simple to complex

See [POSTPROCESSORS.md](POSTPROCESSORS.md) for complete documentation and usage examples.

## Architecture

The system has three layers:

1. **High-level API** (`z3adapter.reasoning`) - Simple Python interface for reasoning tasks
2. **Agentic loop** (`z3adapter.agentic`) - the iterative `z3_solve` ⇄ `finish` tool loop, in-process Z3 executor, and tool-call recovery
3. **Low-level execution** (`z3adapter.backends`) - agentic, JSON DSL, or SMT2 backend for Z3

Most users should use the high-level API.

## Examples

The `examples/` directory contains complete working examples for various use cases:

- **agentic_usage.py** - The agentic SMT-LIB scratchpad loop (new default)
- **simple_usage.py** - Basic usage with OpenAI
- **azure_simple_example.py** - Simple Azure OpenAI integration
- **backend_comparison.py** - Comparing SMT2 vs JSON backends
- **batch_evaluation.py** - Evaluating on datasets
- **postprocessor_example.py** - Using postprocessing techniques

### Running Examples After pip Install

If you installed via `pip install proofofthought`, you can create your own scripts anywhere using the Quick Start examples above. The examples directory is primarily for development and testing.

### Running Examples in Development Mode

If you cloned the repository:

```bash
cd /path/to/proofofthought
python examples/simple_usage.py
```

**Note:** Some examples use helper modules like `utils/azure_config.py` which are only available when running from the repository root.

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