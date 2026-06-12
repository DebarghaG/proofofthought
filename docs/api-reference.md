# API Reference

This reference documents the public API for ProofOfThought.

## ProofOfThought

The main entry point for the reasoning system.

**Location:** `z3adapter.reasoning.proof_of_thought.ProofOfThought`

### Constructor

```python
def __init__(
    self,
    llm_client: Any,
    model: str = "gpt-5",
    backend: Literal["agentic", "json", "smt2"] = "agentic",
    max_attempts: int = 3,
    max_iterations: int = 10,
    verify_timeout: int = 10000,
    optimize_timeout: int = 100000,
    cache_dir: str | None = None,
    z3_path: str = "z3",
    postprocessors: Sequence[str | Postprocessor] | None = None,
    postprocessor_configs: dict[str, dict] | None = None,
    agentic_config: AgenticConfig | None = None,
) -> None
```

**Parameters:**

- `llm_client`: OpenAI/AzureOpenAI client instance (any OpenAI-compatible client)
- `model`: Deployment/model name (default: `"gpt-5"`)
- `backend`: `"agentic"`, `"smt2"`, or `"json"` (default: `"agentic"` — see [Agentic Reasoning](agentic.md))
- `max_attempts`: Retry limit for single-shot generation, json/smt2 only (default: `3`)
- `max_iterations`: Tool-loop turn limit, agentic only (default: `10`)
- `verify_timeout`: Z3 timeout in milliseconds — governs all backends, including the agentic loop's in-process Z3 (default: `10000`)
- `optimize_timeout`: Optimization timeout in ms, JSON only (default: `100000`)
- `cache_dir`: Program cache directory (default: `tempfile.gettempdir()`)
- `z3_path`: Z3 executable path for the SMT2 backend (default: `"z3"`; the agentic backend needs no CLI binary)
- `postprocessors`: Postprocessor names/instances — json/smt2 only; combining with the agentic backend raises `ValueError` at construction
- `agentic_config`: Optional `z3adapter.agentic.AgenticConfig` with full control over the loop. When provided it is **authoritative** — set the model on it (a conflict with `model` logs a warning)

### query()

```python
def query(
    self,
    question: str,
    temperature: float | None = None,
    max_tokens: int = 16384,
    save_program: bool = False,
    program_path: str | None = None,
    enable_postprocessing: bool = True,
) -> QueryResult
```

**Parameters:**

- `question`: Natural language question
- `temperature`: Sampling temperature, honored on **every** backend. `None` (default) sends nothing and uses the provider default — required for models like GPT-5 that reject non-default temperatures
- `max_tokens`: Max completion tokens per LLM response (default: `16384`)
- `save_program`: Save the generated program to disk — for the agentic backend, the final trajectory program (default: `False`)
- `program_path`: Custom save path (default: auto-generated, uniquified, in `cache_dir`)
- `enable_postprocessing`: Apply configured postprocessors, json/smt2 only (default: `True`)

**Returns:** `QueryResult`

On the agentic backend, `query()` runs the iterative `z3_solve` ⇄ `finish` tool loop (see [Agentic Reasoning](agentic.md)). On json/smt2 it runs the classic generate → execute → feedback retry loop bounded by `max_attempts`.

## QueryResult

Contains the results of a reasoning query.

```python
@dataclass
class QueryResult:
    question: str                        # Input question
    answer: bool | None                  # Boolean view of answer_text; None when
                                         #   non-boolean OR no answer (check success)
    json_program: dict[str, Any] | None  # Generated program if JSON backend
    sat_count: int                       # SAT occurrences (agentic: last verdict)
    unsat_count: int                     # UNSAT occurrences (agentic: last verdict)
    output: str                          # Raw Z3 output (agentic: last verdict's)
    success: bool                        # An answer was produced
    num_attempts: int                    # Attempts (json/smt2) / iterations (agentic)
    error: str | None                    # Error message if failed
    answer_text: str | None              # CANONICAL answer, every backend
    smt_history: list | None             # Agentic trajectory: every program + verdict
    iterations: int                      # Agentic tool-loop turns
    verified: bool                       # Agentic: finish backed by a decisive verdict
    proof_status: str | None             # Agentic: "proof_by_contradiction" /
                                         #   "sat_witness" / "unverified"
```

**Field contract** (uniform across backends):

- `answer_text` is the canonical answer — always populated when an answer was produced (`"True"`/`"False"` for json/smt2, the raw `finish()` value for agentic). Prefer it for anything that isn't strictly boolean.
- `answer` is the boolean coercion of `answer_text` via a small unambiguous vocabulary (yes/no/true/false/valid/invalid/verified/violated). Multiple-choice letters, numbers, and raw Z3 verdicts coerce to `None`.
- `success` means "an answer was produced" — it does **not** imply formal verification. Verification strength lives in `verified` and `proof_status`.

## ProofStatus

**Location:** `z3adapter.agentic.ProofStatus` (a `StrEnum`; values serialize as plain strings)

| value | meaning |
|---|---|
| `proof_by_contradiction` | last decisive verdict was a clean `unsat` of the negated candidate — a proof |
| `sat_witness` | last decisive verdict was a clean `sat` — a consistency witness, weaker |
| `unverified` | answer recorded without a usable verdict — an ordinary LLM guess |

See [Agentic Reasoning](agentic.md) for the full protocol, including finish rejection.

## AgenticSolver / AgenticConfig / AgenticResult

The low-level agentic API, usable without `ProofOfThought`.

**Location:** `z3adapter.agentic`

```python
from z3adapter.agentic import AgenticSolver, AgenticConfig

solver = AgenticSolver(client, AgenticConfig(model="gpt-5"))
result = solver.solve(question, answer_format="Answer with one of: Yes, No.",
                      temperature=None, max_tokens=None)  # per-call overrides
```

`AgenticConfig` fields: `model`, `max_tokens`, `temperature` (None = don't send), `max_iterations`, `max_consecutive_nudges`, `max_finish_rejections`, `z3_timeout_ms`, `lenient_extraction`, `system_prompt`.

`AgenticResult` fields: `question`, `answer`, `explanation`, `verified`, `proof_status`, `smt_history`, `messages` (full transcript incl. reasoning channel), `iterations`, `token_usage`, `error`, `extraction_method` (`tool_call_finish` / `tool_call_finish_unverified` / `text_pattern_extracted` / `none`).

## EvaluationPipeline

Facilitates batch evaluation of reasoning questions on datasets.

**Location:** `z3adapter.reasoning.evaluation.EvaluationPipeline`

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

**Scoring:** boolean-like ground truths (bool, 0/1, "true"/"yes"/...) compare via the boolean answer; everything else — multiple choice, free form — compares whitespace/case-normalized `answer_text`. A sample is `failed` only when no answer was produced.

**Caching behavior:**

Results are cached by saving `{sample_id}_result.json` and `{sample_id}_program{ext}` files to `output_dir`. Each result file records `answer`, `answer_text`, `verified`, and `proof_status`, so verified-accuracy can be computed separately from raw accuracy.

## EvaluationMetrics

Provides comprehensive metrics for evaluation results.

```python
@dataclass
class EvaluationMetrics:
    accuracy: float                # correct / (correct + wrong)
    precision: float               # binary metrics: boolean-coercible pairs only
    recall: float
    f1_score: float
    specificity: float
    false_positive_rate: float
    false_negative_rate: float
    tp: int
    fp: int
    tn: int
    fn: int
    total_samples: int             # correct + wrong + failed
    correct_answers: int
    wrong_answers: int
    failed_answers: int            # no answer produced
```

Binary classification metrics (`precision`/`recall`/`f1_score`/the confusion matrix) accumulate **only** for samples where both the answer and the ground truth coerce to booleans; non-boolean datasets still get `accuracy` via text comparison.

## Backend

Defines the abstract interface for execution backends.

**Location:** `z3adapter.backends.abstract.Backend`

### Interface Methods

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

Concrete implementations: `AgenticBackend`, `SMT2Backend`, and `JSONBackend`.

### AgenticBackend.reverify()

```python
def reverify(self, program_path: str, proof_status: ProofStatus | str | None) -> bool
```

Re-runs a saved trajectory program and returns True when it still yields the verdict that backed the original answer (`unsat` for `proof_by_contradiction`, `sat` for `sat_witness`; always False for `unverified`/None). This encapsulates the negation polarity — `execute()`'s `answer` field reports *program-level* satisfiability (`sat → True`), which for a contradiction proof is **not** the question's answer.

## VerificationResult

Encapsulates the results of Z3 verification execution.

```python
@dataclass
class VerificationResult:
    answer: bool | None  # Program-level: True (SAT), False (UNSAT), None (ambiguous/error)
    sat_count: int
    unsat_count: int
    output: str          # Raw execution output
    success: bool        # Execution completed without exception
    error: str | None    # Error message if failed
```

## Z3ProgramGenerator

Handles LLM-based single-shot program generation with error recovery (json/smt2 backends).

**Location:** `z3adapter.reasoning.program_generator.Z3ProgramGenerator`

### generate()

```python
def generate(
    self,
    question: str,
    temperature: float | None = None,
    max_tokens: int = 16384,
) -> GenerationResult
```

`temperature` is only sent to the API when explicitly set; `None` uses the provider default (GPT-5-safe).

### generate_with_feedback()

Enables multi-turn conversation with error feedback:

```python
messages=[
    {"role": "user", "content": prompt},
    {"role": "assistant", "content": previous_response},
    {"role": "user", "content": feedback_message},
]
```

## Utility: Azure Config

Provides convenient configuration for Azure OpenAI deployments.

**Location:** `utils.azure_config.get_client_config()`

**Returns:**
```python
{
    "llm_client": AzureOpenAI(...),
    "model": str  # Deployment name from env
}
```

**Required environment variables:**

- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_VERSION`
- `AZURE_GPT5_DEPLOYMENT_NAME` or `AZURE_GPT4O_DEPLOYMENT_NAME`
