# Examples

This page demonstrates common usage patterns through example scripts.

All examples are located in the `examples/` directory and should be run from the project root:

```bash
python examples/{script}.py
```

## Basic Query

The simplest way to use ProofOfThought is through a single query.

**File:** `examples/simple_usage.py`

```python
from openai import OpenAI
from z3adapter.reasoning import ProofOfThought

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
pot = ProofOfThought(llm_client=client, model="gpt-4o")

result = pot.query("Would Nancy Pelosi publicly denounce abortion?")
print(result.answer)  # False
```

## Azure OpenAI

For Azure OpenAI deployments, use the provided configuration utility.

**File:** `examples/azure_simple_example.py`

```python
from utils.azure_config import get_client_config
from z3adapter.reasoning import ProofOfThought

config = get_client_config()
pot = ProofOfThought(llm_client=config["llm_client"], model=config["model"])

result = pot.query("Can fish breathe underwater?")
print(result.answer)  # True
```

## Backend Comparison

You can compare how the two backends perform on the same question.

**File:** `examples/backend_comparison.py`

```python
config = get_client_config()
question = "Can fish breathe underwater?"

pot_json = ProofOfThought(llm_client=config["llm_client"], backend="json")
pot_smt2 = ProofOfThought(llm_client=config["llm_client"], backend="smt2")

result_json = pot_json.query(question)
result_smt2 = pot_smt2.query(question)

print(f"JSON: {result_json.answer}")
print(f"SMT2: {result_smt2.answer}")
```

## Batch Evaluation

For evaluating multiple questions from a dataset, use the evaluation pipeline.

**File:** `examples/batch_evaluation.py`

```python
from z3adapter.reasoning import EvaluationPipeline, ProofOfThought

pot = ProofOfThought(llm_client=client)
evaluator = EvaluationPipeline(proof_of_thought=pot, output_dir="results/")

result = evaluator.evaluate(
    dataset="data/strategyQA_train.json",
    question_field="question",
    answer_field="answer",
    max_samples=100
)

print(f"Accuracy: {result.metrics.accuracy:.2%}")
print(f"F1 Score: {result.metrics.f1_score:.4f}")
```

## Azure + SMT2 Evaluation

This example combines Azure OpenAI with the SMT2 backend for batch evaluation.

**File:** `examples/batch_evaluation_smt2_azure.py`

```python
config = get_client_config()

pot = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="smt2"
)

evaluator = EvaluationPipeline(proof_of_thought=pot)
result = evaluator.evaluate("data/strategyQA_train.json", max_samples=50)
```

## Full Benchmark Suite

For comprehensive benchmarking, the experiments pipeline runs all datasets with both backends.

**File:** `experiments_pipeline.py`

This script runs all 5 benchmarks (ProntoQA, FOLIO, ProofWriter, ConditionalQA, StrategyQA) with both backends:

```bash
python experiments_pipeline.py
```

**Implementation details:**

- Modifies `benchmark/bench_*.py` files to set the backend via regex substitution
- Runs each benchmark script as a subprocess with a 1-hour timeout
- Collects metrics from `output/{backend}_evaluation_{benchmark}/` directories
- Generates a markdown table and updates README.md with results

**Configuration** (`experiments_pipeline.py:29-41`):
```python
BENCHMARKS = {
    "prontoqa": "benchmark/bench_prontoqa.py",
    "folio": "benchmark/bench_folio.py",
    "proofwriter": "benchmark/bench_proofwriter.py",
    "conditionalqa": "benchmark/bench_conditionalqa.py",
    "strategyqa": "benchmark/bench_strategyqa.py",
}
BACKENDS = ["smt2", "json"]
```

## Benchmark Script Structure

Individual benchmark scripts follow a common pattern, illustrated here with StrategyQA.

**File:** `benchmark/bench_strategyqa.py`

```python
config = get_client_config()

pot = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend=BACKEND,  # Modified by experiments_pipeline.py
    max_attempts=3,
    cache_dir=f"output/{BACKEND}_programs_strategyqa",
)

evaluator = EvaluationPipeline(
    proof_of_thought=pot,
    output_dir=f"output/{BACKEND}_evaluation_strategyqa",
    num_workers=10,  # ThreadPoolExecutor for parallel processing
)

result = evaluator.evaluate(
    dataset="data/strategyQA_train.json",
    id_field="qid",
    max_samples=100,
    skip_existing=True,  # Resume interrupted runs
)
```

## Dataset Format

Datasets should be formatted as JSON arrays of objects:

```json
[
  {
    "question": "Can fish breathe underwater?",
    "answer": true
  },
  {
    "question": "Do humans have wings?",
    "answer": false
  }
]
```

You can optionally include an ID field:

```json
{"qid": "sample_123", "question": "...", "answer": true}
```

Use the `question_field`, `answer_field`, and `id_field` parameters to specify custom field names.

## Saving Programs

To save generated programs to disk for inspection:

```python
result = pot.query(
    "Can fish breathe underwater?",
    save_program=True,
    program_path="output/my_program.smt2"
)
```

If you don't specify a path, the default is: `{cache_dir}/{auto_generated}{ext}`

## Advanced Configuration

For more control over the reasoning process, you can customize various parameters:

```python
pot = ProofOfThought(
    llm_client=client,
    model="gpt-5",
    backend="smt2",
    max_attempts=5,           # More retries
    verify_timeout=20000,     # 20s timeout
    z3_path="/custom/z3"      # Custom Z3 binary
)
```
