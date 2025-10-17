# API Reference

## ProofOfThought

`z3adapter.reasoning.proof_of_thought.ProofOfThought`

### Constructor

```python
def __init__(
    self,
    llm_client: Any,
    model: str = "gpt-5",
    backend: Literal["json", "smt2"] = "smt2",
    max_attempts: int = 3,
    verify_timeout: int = 10000,
    optimize_timeout: int = 100000,
    cache_dir: str | None = None,
    z3_path: str = "z3",
) -> None
```

**Parameters:**

- `llm_client`: OpenAI/AzureOpenAI client instance
- `model`: Deployment/model name (default: `"gpt-5"`)
- `backend`: `"json"` or `"smt2"` (default: `"smt2"`)
- `max_attempts`: Retry limit for generation (default: `3`)
- `verify_timeout`: Z3 timeout in milliseconds (default: `10000`)
- `optimize_timeout`: Optimization timeout in ms, JSON only (default: `100000`)
- `cache_dir`: Program cache directory (default: `tempfile.gettempdir()`)
- `z3_path`: Z3 executable path for SMT2 (default: `"z3"`)

### query()

```python
def query(
    self,
    question: str,
    temperature: float = 0.1,
    max_tokens: int = 16384,
    save_program: bool = False,
    program_path: str | None = None,
) -> QueryResult
```

**Parameters:**

- `question`: Natural language question
- `temperature`: LLM temperature (default: `0.1`, ignored for GPT-5 which only supports `1.0`)
- `max_tokens`: Max completion tokens (default: `16384`)
- `save_program`: Save generated program to disk (default: `False`)
- `program_path`: Custom save path (default: auto-generated in `cache_dir`)

**Returns:** `QueryResult`

**Implementation:** Retry loop with error feedback

```python
for attempt in range(1, max_attempts + 1):
    if attempt == 1:
        gen_result = self.generator.generate(question, temperature, max_tokens)
    else:
        gen_result = self.generator.generate_with_feedback(
            question, error_trace, previous_response, temperature, max_tokens
        )
    # ... execute and check result
```

## QueryResult

```python
@dataclass
class QueryResult:
    question: str                        # Input question
    answer: bool | None                  # True (SAT), False (UNSAT), None (ambiguous/error)
    json_program: dict[str, Any] | None  # Generated program if JSON backend
    sat_count: int                       # SAT occurrences in output
    unsat_count: int                     # UNSAT occurrences
    output: str                          # Raw Z3 output
    success: bool                        # Execution completed
    num_attempts: int                    # Generation attempts used
    error: str | None                    # Error message if failed
```

## EvaluationPipeline

`z3adapter.reasoning.evaluation.EvaluationPipeline`

### Constructor

```python
def __init__(
    self,
    proof_of_thought: ProofOfThought,
    output_dir: str = "evaluation_results",
    num_workers: int = 1,
) -> None
```

**Parameters:**

- `proof_of_thought`: Configured ProofOfThought instance
- `output_dir`: Results directory (default: `"evaluation_results"`)
- `num_workers`: Parallel workers (default: `1`, uses `ThreadPoolExecutor` if `> 1`)

### evaluate()

```python
def evaluate(
    self,
    dataset: list[dict[str, Any]] | str,
    question_field: str = "question",
    answer_field: str = "answer",
    id_field: str | None = None,
    max_samples: int | None = None,
    skip_existing: bool = True,
) -> EvaluationResult
```

**Parameters:**

- `dataset`: JSON file path or list of dicts
- `question_field`: Field name for question text (default: `"question"`)
- `answer_field`: Field name for ground truth (default: `"answer"`)
- `id_field`: Field for sample ID (default: `None`, auto-generates `sample_{idx}`)
- `max_samples`: Limit samples (default: `None`, all)
- `skip_existing`: Skip cached results (default: `True`)

**Returns:** `EvaluationResult`

**Caching:** Saves `{sample_id}_result.json` and `{sample_id}_program{ext}` to `output_dir`

## EvaluationMetrics

```python
@dataclass
class EvaluationMetrics:
    accuracy: float                # sklearn.metrics.accuracy_score
    precision: float               # sklearn.metrics.precision_score (zero_division=0)
    recall: float                  # sklearn.metrics.recall_score (zero_division=0)
    f1_score: float                # 2 * (P * R) / (P + R)
    specificity: float             # TN / (TN + FP)
    false_positive_rate: float     # FP / (FP + TN)
    false_negative_rate: float     # FN / (FN + TP)
    tp: int                        # True positives
    fp: int                        # False positives
    tn: int                        # True negatives
    fn: int                        # False negatives
    total_samples: int             # Correct + wrong + failed
    correct_answers: int           # answer == ground_truth
    wrong_answers: int             # answer != ground_truth
    failed_answers: int            # success == False
```

Computed via `sklearn.metrics.confusion_matrix` for binary classification.

## Backend

`z3adapter.backends.abstract.Backend`

Abstract interface:

```python
class Backend(ABC):
    @abstractmethod
    def execute(self, program_path: str) -> VerificationResult:
        pass

    @abstractmethod
    def get_file_extension(self) -> str:
        pass

    @abstractmethod
    def get_prompt_template(self) -> str:
        pass

    def determine_answer(self, sat_count: int, unsat_count: int) -> bool | None:
        if sat_count > 0 and unsat_count == 0:
            return True
        elif unsat_count > 0 and sat_count == 0:
            return False
        else:
            return None
```

Implementations: `SMT2Backend`, `JSONBackend`

## VerificationResult

```python
@dataclass
class VerificationResult:
    answer: bool | None  # True (SAT), False (UNSAT), None (ambiguous/error)
    sat_count: int
    unsat_count: int
    output: str          # Raw execution output
    success: bool        # Execution completed without exception
    error: str | None    # Error message if failed
```

## Z3ProgramGenerator

`z3adapter.reasoning.program_generator.Z3ProgramGenerator`

### generate()

```python
def generate(
    self,
    question: str,
    temperature: float = 0.1,
    max_tokens: int = 16384,
) -> GenerationResult
```

**LLM API Call:**

```python
response = self.llm_client.chat.completions.create(
    model=self.model,
    messages=[{"role": "user", "content": prompt}],
    max_completion_tokens=max_tokens,
)
```

Note: `temperature` parameter not passed (GPT-5 constraint).

### generate_with_feedback()

Multi-turn conversation with error feedback:

```python
messages=[
    {"role": "user", "content": prompt},
    {"role": "assistant", "content": previous_response},
    {"role": "user", "content": feedback_message},
]
```

## Utility: Azure Config

`utils.azure_config.get_client_config()`

Returns:
```python
{
    "llm_client": AzureOpenAI(...),
    "model": str  # Deployment name from env
}
```

Required environment variables:
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_VERSION`
- `AZURE_GPT5_DEPLOYMENT_NAME` or `AZURE_GPT4O_DEPLOYMENT_NAME`
