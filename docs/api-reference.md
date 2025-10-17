# API Reference

## ProofOfThought

Main API for Z3-based reasoning.

```python
from z3adapter.reasoning import ProofOfThought
```

### Constructor

```python
ProofOfThought(
    llm_client,
    model="gpt-5",
    backend="smt2",
    max_attempts=3,
    verify_timeout=10000,
    optimize_timeout=100000,
    cache_dir=None,
    z3_path="z3"
)
```

**Parameters:**

- `llm_client` - OpenAI, AzureOpenAI, or compatible LLM client
- `model` (str) - Model/deployment name (default: "gpt-5")
- `backend` (str) - Execution backend: "smt2" or "json" (default: "smt2")
- `max_attempts` (int) - Max retries for program generation (default: 3)
- `verify_timeout` (int) - Z3 verification timeout in ms (default: 10000)
- `optimize_timeout` (int) - Z3 optimization timeout in ms (default: 100000)
- `cache_dir` (str|None) - Directory for caching programs (default: temp dir)
- `z3_path` (str) - Path to Z3 executable for SMT2 backend (default: "z3")

### query()

Ask a reasoning question.

```python
result = pot.query(
    question,
    max_attempts=None,
    save_program=False
)
```

**Parameters:**

- `question` (str) - Natural language question
- `max_attempts` (int|None) - Override max attempts for this query
- `save_program` (bool) - Save generated program to disk (default: False)

**Returns:** `QueryResult`

```python
@dataclass
class QueryResult:
    question: str           # Original question
    answer: bool | None     # True, False, or None if error
    json_program: dict | None  # Generated program (if JSON backend)
    sat_count: int          # Number of SAT results
    unsat_count: int        # Number of UNSAT results
    output: str             # Raw Z3 output
    success: bool           # Did query complete?
    num_attempts: int       # Attempts taken
    error: str | None       # Error message if failed
```

**Example:**

```python
result = pot.query("Can fish breathe underwater?")
print(result.answer)  # True
print(f"Took {result.num_attempts} attempts")
```

## EvaluationPipeline

Batch evaluation on datasets.

```python
from z3adapter.reasoning import EvaluationPipeline
```

### Constructor

```python
EvaluationPipeline(
    proof_of_thought,
    output_dir="results/"
)
```

**Parameters:**

- `proof_of_thought` (ProofOfThought) - Configured ProofOfThought instance
- `output_dir` (str) - Directory for saving results (default: "results/")

### evaluate()

Run evaluation on a dataset.

```python
result = evaluator.evaluate(
    dataset,
    question_field="question",
    answer_field="answer",
    max_samples=None,
    save_results=True
)
```

**Parameters:**

- `dataset` (str) - Path to JSON dataset
- `question_field` (str) - JSON field containing questions (default: "question")
- `answer_field` (str) - JSON field containing answers (default: "answer")
- `max_samples` (int|None) - Limit number of samples (default: all)
- `save_results` (bool) - Save detailed results to disk (default: True)

**Returns:** `EvaluationResult`

```python
@dataclass
class EvaluationResult:
    metrics: EvaluationMetrics
    predictions: list
    dataset_name: str
    timestamp: str
```

**EvaluationMetrics:**

```python
@dataclass
class EvaluationMetrics:
    accuracy: float       # Percentage correct
    precision: float      # True positives / (TP + FP)
    recall: float         # True positives / (TP + FN)
    f1: float            # Harmonic mean of precision/recall
    success_rate: float  # Percentage of queries that completed
    total_samples: int
    correct: int
    incorrect: int
    failed: int
```

**Example:**

```python
from z3adapter.reasoning import ProofOfThought, EvaluationPipeline

pot = ProofOfThought(llm_client=client)
evaluator = EvaluationPipeline(proof_of_thought=pot)

result = evaluator.evaluate(
    dataset="data/strategyQA_train.json",
    max_samples=100
)

print(f"Accuracy: {result.metrics.accuracy:.2%}")
print(f"F1 Score: {result.metrics.f1:.4f}")
```

## Data Classes

### QueryResult

Returned by `ProofOfThought.query()`.

**Fields:**

- `question` (str) - The input question
- `answer` (bool|None) - Reasoning result (True/False/None)
- `json_program` (dict|None) - Generated program if using JSON backend
- `sat_count` (int) - Number of SAT (satisfiable) results
- `unsat_count` (int) - Number of UNSAT (unsatisfiable) results
- `output` (str) - Raw Z3 output
- `success` (bool) - Whether execution succeeded
- `num_attempts` (int) - Generation attempts used
- `error` (str|None) - Error message if failed

### VerificationResult

Low-level result from backend execution.

```python
from z3adapter.backends.abstract import VerificationResult
```

**Fields:**

- `answer` (bool|None) - True (SAT), False (UNSAT), None (error)
- `sat_count` (int) - Count of SAT results
- `unsat_count` (int) - Count of UNSAT results
- `output` (str) - Raw execution output
- `success` (bool) - Execution completed
- `error` (str|None) - Error message

## Azure OpenAI Helper

Utility for Azure OpenAI configuration.

```python
from utils.azure_config import get_client_config
```

### get_client_config()

Returns configured Azure OpenAI client and settings.

```python
config = get_client_config()
```

**Returns:** `dict`

```python
{
    "llm_client": AzureOpenAI(...),  # Configured client
    "model": "gpt-5"                 # Deployment name
}
```

**Environment variables required:**

```bash
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://....openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_GPT5_DEPLOYMENT_NAME=gpt-5
```

**Example:**

```python
from utils.azure_config import get_client_config
from z3adapter.reasoning import ProofOfThought

config = get_client_config()
pot = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"]
)
```

## Low-Level Components

Most users won't need these—use `ProofOfThought` instead.

### Z3ProgramGenerator

Generates Z3 programs from natural language.

```python
from z3adapter.reasoning import Z3ProgramGenerator
```

### Z3Verifier

Executes and verifies Z3 programs.

```python
from z3adapter.reasoning import Z3Verifier
```

### Backends

Backend implementations.

```python
from z3adapter.backends import JSONBackend, SMT2Backend
```

See [Backends](backends.md) for details.
