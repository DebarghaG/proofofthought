# Examples

All examples live in `examples/` and should be run from the repository root:

```bash
python examples/<script>.py
```

## Basic Query

**File:** `examples/simple_usage.py`

Use this first if you want the shortest path to a working SMT-LIB-backed query.

```python
from openai import OpenAI
from proofofthought import ProofOfThought

client = OpenAI(api_key="...")
pot = ProofOfThought(llm_client=client)

result = pot.query(
    "Would Nancy Pelosi publicly denounce abortion?",
    save_program=True,
    program_path="output/simple_usage.smt2",
    save_artifact=True,
    artifact_path="output/simple_usage.artifact.json",
)

print(result.answer)
print(result.program_path)
print(result.artifact.completed_stages)
```

## Incremental Staged Workflow

**File:** `examples/backend_comparison.py`

This example now compares:

- the one-shot convenience path
- the explicit staged artifact workflow

Use it when you want to understand how the same question can be built stage by stage and resumed later.

## Azure OpenAI

**File:** `examples/azure_simple_example.py`

Use this for the same flow with Azure OpenAI configuration loaded from the repo helpers.

## Batch Evaluation

**File:** `examples/batch_evaluation.py`

Evaluate a dataset with the default staged path:

```python
from proofofthought import EvaluationPipeline, ProofOfThought

pot = ProofOfThought(llm_client=client)
evaluator = EvaluationPipeline(proof_of_thought=pot, output_dir="results/")

result = evaluator.evaluate(
    dataset="data/strategyQA_train.json",
    question_field="question",
    answer_field="answer",
    max_samples=100,
)
```

## Document-Grounded Verification

**File:** `examples/nl_smt_bench_document_verification.py`

This is the advanced staged SMT-LIB workflow for document models and QA-pair verification. Use it when you need chunked document formalization rather than single-question reasoning.

## Agent Guardrails And Audits

**File:** `examples/agent_guardrail_audit.py`

This example shows the staged foundation pattern for pre-action tool-call checks and post-hoc trajectory auditing over trace entries.

## Code Verification

**File:** `examples/code_contract_verification.py`

This example shows how to build a reusable foundation from code plus contracts/invariants, then run a check against that foundation.

## Postprocessors

**File:** `examples/postprocessor_example.py`

Shows how to combine the staged query path with techniques such as self-refine and self-consistency.

## Legacy Line

If you need the pre-major release behavior, see the archived `1.0.1` docs at `/v1.0.1/`.
