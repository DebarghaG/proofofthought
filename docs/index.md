# ProofOfThought

ProofOfThought `2.0.0` is a staged-SMT verification library. The default workflow is now: build a staged foundation, inspect or persist it over time, and execute repeated checks with Z3 when you want an answer.

The shared mental model is:

**foundation + scenario/trace + checks + execution**

## Release Channels

- **Stable installs** use `pip install proofofthought`
- **Nightly installs** use `pip install --pre proofofthought`

Nightly builds are published from the current `main` branch and may contain breaking changes. Nightly-specific documentation is available at [the nightly docs site](https://debarghaG.github.io/proofofthought/nightly/).

## Version Guide

- **Latest major line**: this site (`2.0.0`)
- **Legacy stable line**: [`1.0.1` docs](https://debarghaG.github.io/proofofthought/v1.0.1/)

If you are migrating older code or looking for the removed JSON backend, use the `1.0.1` docs.

## Core Architecture

```
Question + optional source text
    ↓
Staged artifact construction
    ↓
Stage outputs + resumable context
    ↓
Composed SMT-LIB program
    ↓
Z3 execution
    ↓
SAT / UNSAT / ambiguous
```

The simple `query()` API now runs this staged pipeline for you automatically.

## Main Components

- **`ProofOfThought`**: high-level staged orchestrator for one-shot queries, reusable foundations, and explicit artifact workflows
- **`StagedArtifact`**: durable state object that stores stage outputs, serialized context, and execution results
- **`StagedSMT2Backend`**: staged execution backend used by both the high-level facade and expert workflows
- **`EvaluationPipeline`**: batch evaluation and metrics aggregation

## Quick Start

```python
from openai import OpenAI
from proofofthought import ProofOfThought

client = OpenAI(api_key="...")
pot = ProofOfThought(llm_client=client)
result = pot.query("Would Nancy Pelosi publicly denounce abortion?")

print(result.answer)
print(result.artifact.completed_stages)
```

## Main Workloads

- policy and document guardrails
- agent action validation and trace auditing
- code verification with contracts and invariants

See [Verification Modes](verification-modes.md) for how these all map onto the same staged artifact API.

## Benchmark Snapshot

The repository includes benchmark harnesses for ProntoQA, FOLIO, ProofWriter, ConditionalQA, and StrategyQA. The major release treats the staged pipeline as the product path, while `1.0.1` preserves the older line.

See [Benchmarks](benchmarks.md) for the benchmark tables and [Backends](backends.md) for the current backend guidance.
