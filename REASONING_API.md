# Reasoning API

## Overview

Simple Python API for LLM-based reasoning with Z3 theorem proving. Inspired by DSPy.

## API

### ProofOfThought

```python
from openai import OpenAI
from z3adapter.reasoning import ProofOfThought

client = OpenAI(api_key="...")
pot = ProofOfThought(
    llm_client=client,
    model="gpt-4o",
    max_attempts=3,
    verify_timeout=10000
)

result = pot.query("Your question here")
print(result.answer)  # True/False/None
```

### EvaluationPipeline

```python
from z3adapter.reasoning import EvaluationPipeline

evaluator = EvaluationPipeline(pot, output_dir="results/")
result = evaluator.evaluate(
    dataset="data.json",
    max_samples=100
)

print(f"Accuracy: {result.metrics.accuracy:.2%}")
print(f"F1: {result.metrics.f1_score:.4f}")
```

## Result Objects

**QueryResult:**
- `answer: bool | None` - The answer
- `success: bool` - Query succeeded
- `num_attempts: int` - Attempts taken
- `error: str | None` - Error if failed

**EvaluationMetrics:**
- accuracy, precision, recall, f1_score
- tp, fp, tn, fn (confusion matrix)
- total_samples, correct_answers, wrong_answers, failed_answers

## Error Handling

Automatic retry with feedback for:
- JSON extraction failures
- Z3 execution errors
- Ambiguous results (SAT + UNSAT)
- LLM API errors
