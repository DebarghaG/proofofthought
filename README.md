# ProofOfThought

[![Python 3.10+-](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Z3](https://img.shields.io/badge/Z3-4.15+-green.svg)](https://github.com/Z3Prover/z3)
[![OpenAI](https://img.shields.io/badge/OpenAI-Compatible-412991.svg)](https://platform.openai.com/)
[![Azure](https://img.shields.io/badge/Azure-GPT--4o/GPT--5-0078D4.svg)](https://azure.microsoft.com/en-us/products/ai-services/openai-service)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Staged SMT-LIB reasoning and verification with Z3.

The core product model is:

**foundation + scenario/trace + checks + execution**

## Features

- **Staged By Default**: `ProofOfThought` now builds and executes a staged artifact by default
- **Easy One-Shot Path**: `query()` still works, but it is now a convenience wrapper over the staged pipeline
- **Deep Stage Control**: Create, save, load, inspect, and rerun individual stages over time
- **Azure OpenAI Integration**: Native support for Azure GPT-4o and GPT-5 models
- **Comprehensive Benchmarks**: Evaluated on 5 reasoning datasets (ProntoQA, FOLIO, ProofWriter, ConditionalQA, StrategyQA)
- **High-level API**: Simple Python interface for staged reasoning tasks
- **Batch Evaluation Pipeline**: Built-in tools for dataset evaluation and metrics
- **Postprocessing Techniques**: Self-Refine, Self-Consistency, Decomposed Prompting, and Least-to-Most Prompting for enhanced reasoning quality

## Project Status

- **Current release line**: `2.0.0`
- **Core product API**: staged artifact workflow via `ProofOfThought`
- **Compatibility alias**: `backend="smt2"` now routes to the staged implementation
- **Removed**: `backend="json"` from the public API

If you need the older stable line that is currently available, use the archived `1.0.1` docs at `/v1.0.1/`.

## Release Channels

- **Stable**: `pip install proofofthought`
- **Nightly**: `pip install --pre proofofthought`

Nightly releases are built from the current `main` branch and may contain breaking changes. They use PyPI prerelease versions in the form `BASE.devYYYYMMDDHHMM`.
Release notes for the currently published nightly are documented at <https://debarghaG.github.io/proofofthought/nightly/release-notes/>.

## Installation

### Stable From PyPI

Install the latest stable release:

```bash
pip install proofofthought
```

### Nightly From PyPI

Install the latest nightly prerelease:

```bash
pip install --pre proofofthought
```

To pin a specific nightly once it has been published:

```bash
pip install "proofofthought==2.0.0.dev202604011230"
```

Nightly builds are intentionally unstable and may change behavior without a stable compatibility guarantee.

**Canonical import:**
```python
from proofofthought import ProofOfThought
```

`z3adapter` remains available as a compatibility alias during the migration window for this major line.

### From Source (Development)

For contributing or using the latest development version:

```bash
git clone https://github.com/debarghaG/proofofthought.git
cd proofofthought
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

### Prerequisites

- Python 3.10+
- An OpenAI API key or Azure OpenAI endpoint
- Z3 solver (`z3-solver` installs the `z3` binary into the active virtual environment)
- For nightly documentation, see <https://debarghaG.github.io/proofofthought/nightly/>

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
AZURE_API_VERSION=2024-12-01-preview
```

You can also set these as system environment variables instead of using a `.env` file.

## Quick Start

### One-Shot Convenience Path

```python
import os
from dotenv import load_dotenv
from openai import OpenAI
from proofofthought import ProofOfThought

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
pot = ProofOfThought(llm_client=client, model="gpt-4o")

result = pot.query(
    "Would Nancy Pelosi publicly denounce abortion?",
    save_program=True,
    save_artifact=True,
    artifact_path="output/pelosi.artifact.json",
)

print(result.answer)
print(result.artifact.artifact_path)
```

### Explicit Staged Workflow

```python
from proofofthought import ProofOfThought

pot = ProofOfThought(llm_client=client, model="gpt-4o")

artifact = pot.build_artifact(
    text="All humans are mortal. Socrates is a human.",
    question="Is Socrates mortal?",
    through_stage="knowledge_base",
)

pot.run_stage(artifact, "scenario", rerun_downstream=True)
pot.save_artifact(artifact, "output/socrates.artifact.json")

result = pot.execute_artifact(artifact, save_program=True, program_path="output/socrates.smt2")
print(result.answer)
```

## Batch Evaluation

```python
from proofofthought import EvaluationPipeline, ProofOfThought

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

The major release is staged-first:

```python
# Default staged path
pot = ProofOfThought(llm_client=client)

# Explicit staged backend
pot = ProofOfThought(llm_client=client, backend="staged_smt2")

# Compatibility alias to the same staged implementation
pot = ProofOfThought(llm_client=client, backend="smt2")
```

If you need the removed JSON backend, use the legacy `1.0.1` release line and docs.

## Reusable Foundations

The staged artifact model is designed for repeated checks over the same foundation:

```python
from proofofthought import ProofOfThought

pot = ProofOfThought(llm_client=client, model="gpt-4o")

policy = pot.build_foundation(
    text="All wire transfers above 10000 USD require dual approval.",
    source_kind="policy",
)

first_check = pot.run_check(
    policy,
    question="Can the agent submit a 25000 USD wire transfer?",
    scenario_text="The transfer has only one approval.",
    check_name="wire_transfer_guardrail",
)

second_check = pot.run_check(
    policy,
    question="Can the agent submit a 25000 USD wire transfer?",
    scenario_text="The transfer has two approvals.",
    check_name="wire_transfer_guardrail_retry",
)
```

## Agent Guardrails And Audits

The same staged artifact model supports both pre-action agent guardrails and post-hoc trajectory audits:

```python
foundation = pot.build_foundation(
    text="Agents may not execute withdrawals larger than the available balance.",
    source_kind="policy",
)

guardrail = pot.run_check(
    foundation,
    question="May the agent call withdraw?",
    scenario_text="The agent proposes withdraw(amount=50) with available_balance=20.",
    check_name="withdraw_guardrail",
)

audit = pot.fork_artifact(
    foundation,
    artifact_kind="audit",
    question="Did the executed trace violate policy?",
)
pot.add_trace_entry(audit, "available_balance=20", entry_type="observation")
pot.add_trace_entry(audit, "withdraw(amount=50)", entry_type="action")

audit_result = pot.run_check(
    audit,
    question="Does the trace violate the balance invariant?",
    check_name="withdraw_audit",
)
```

Use this shape for:

- tool-call guardrails before execution
- replay and audit of agent trajectories
- reusable policy foundations across many checks

## Code Verification

Code verification uses the same staged artifact model. Build a foundation from code plus explicit contracts, then run checks against that reusable foundation:

```python
from proofofthought import ProofOfThought

pot = ProofOfThought(llm_client=client, model="gpt-4o")

code_foundation = pot.build_foundation(
    text="""
def transfer(balance: int, amount: int) -> int:
    return balance - amount
""",
    source_kind="code",
    annotations={
        "preconditions": ["amount >= 0", "amount <= balance"],
        "postconditions": ["result == balance - amount"],
        "invariants": ["balance >= 0"],
    },
)

result = pot.run_check(
    code_foundation,
    question="Can transfer return a negative balance?",
    scenario_text="Assume balance = 20 and amount = 50.",
    check_name="transfer_contract_check",
)

print(result.answer)
```

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

See [docs/postprocessors.md](docs/postprocessors.md) for complete documentation and usage examples.

## Architecture

The public product story has two layers:

1. **High-level staged API** (`proofofthought`) for one-shot queries, reusable foundations, and persisted artifacts
2. **Deep staged APIs** (`proofofthought.backends.smt2`) for explicit stage control, IR inspection, and document-grounded workflows

## Examples

The `examples/` directory contains complete working examples for various use cases:

- **simple_usage.py** - Basic usage with OpenAI
- **code_contract_verification.py** - Reusable code foundation plus contract checks
- **azure_simple_example.py** - Simple Azure OpenAI integration
- **batch_evaluation.py** - Evaluating on datasets
- **nl_smt_bench_document_verification.py** - Document-grounded staged SMT-LIB verification
- **postprocessor_example.py** - Using postprocessing techniques
- **backend_comparison.py** - Comparing one-shot convenience usage with explicit staged control

### Running Examples After pip Install

If you installed via `pip install proofofthought`, you can create your own scripts anywhere using the Quick Start examples above. The examples directory is primarily for development and testing.

### Running Examples in Development Mode

If you cloned the repository:

```bash
cd /path/to/proofofthought
source venv/bin/activate
python examples/simple_usage.py
```

**Note:** Run examples from the repository root with the project virtual environment activated so both `proofofthought` and `venv/bin/z3` are available.

## Running Experiments

You can use this repository as a strong baseline for LLM+Solver methods. This code is generally benchmarked with GPT-5 on the first 100 samples of 5 datasets, as an indicator of whether we broke something during development. These numbers are not the best, and you can certainly get better numbers with better prompt engineering with this same tooling. Please feel free to put in a PR if you get better numbers with modified prompts.

To run all benchmarks with both backends and generate results:

```bash
python experiments_pipeline.py
```

This will:
- Run all 5 benchmarks (ProntoQA, FOLIO, ProofWriter, ConditionalQA, StrategyQA)
- Regenerate the benchmark tables in `results/`
- Exercise the staged-major line rather than the removed JSON path
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
