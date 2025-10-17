# Benchmarks

This page presents evaluation results on 5 logical reasoning datasets using Azure GPT-5.

## Methodology

The evaluation follows a consistent methodology across all datasets.

**Model:** Azure GPT-5 deployment

**Configuration:**
- `max_attempts=3` (retry with error feedback)
- `verify_timeout=10000ms`
- `optimize_timeout=100000ms` (JSON backend only)
- `num_workers=10` (ThreadPoolExecutor for parallel processing)

**Metrics** (computed via `sklearn.metrics`):

- **Accuracy:** `accuracy_score(y_true, y_pred)`
- **Precision:** `precision_score(y_true, y_pred, zero_division=0)`
- **Recall:** `recall_score(y_true, y_pred, zero_division=0)`
- **F1:** `2 * (precision * recall) / (precision + recall)`
- **Success Rate:** `(total - failed) / total`

**Execution:** The `experiments_pipeline.py` script runs all benchmarks sequentially, modifying the `BACKEND` variable in each `benchmark/bench_*.py` script via regex substitution.

## Results

Results from the most recent benchmark run.

**Last Updated:** 2025-10-16 18:14:07

| Benchmark | Backend | Samples | Accuracy | Precision | Recall | F1 Score | Success Rate |
|-----------|---------|---------|----------|-----------|--------|----------|--------------|
| ProntoQA | SMT2 | 100 | 100.00% | 1.0000 | 1.0000 | 1.0000 | 100.00% |
| FOLIO | SMT2 | 100 | 69.00% | 0.6949 | 0.7736 | 0.7321 | 99.00% |
| ProofWriter | SMT2 | 96 | 98.96% | 1.0000 | 1.0000 | 1.0000 | 98.96% |
| ConditionalQA | SMT2 | 100 | 83.00% | 0.9375 | 0.8219 | 0.8759 | 100.00% |
| StrategyQA | SMT2 | 100 | 84.00% | 0.8205 | 0.7805 | 0.8000 | 100.00% |
| ProntoQA | JSON | 100 | 99.00% | 1.0000 | 0.9815 | 0.9907 | 100.00% |
| FOLIO | JSON | 100 | 76.00% | 0.7619 | 0.9412 | 0.8421 | 94.00% |
| ProofWriter | JSON | 96 | 95.83% | 1.0000 | 1.0000 | 1.0000 | 95.83% |
| ConditionalQA | JSON | 100 | 76.00% | 0.9180 | 0.8750 | 0.8960 | 89.00% |
| StrategyQA | JSON | 100 | 68.00% | 0.7500 | 0.7895 | 0.7692 | 86.00% |

## Dataset Characteristics

Each dataset tests different aspects of logical reasoning.

### ProntoQA

ProntoQA features synthetic first-order logic problems with deterministic inference.

**Example:**
```
Facts: "Stella is a lion. All lions are brown."
Question: "Is Stella brown?"
Answer: True
```

**Performance:**

- SMT2: 100% (100/100)
- JSON: 99% (99/100)

Both backends achieve near-perfect results, making this the simplest dataset in the benchmark suite.

### FOLIO

FOLIO presents first-order logic problems derived from Wikipedia articles.

**Characteristics:** Features complex nested quantifiers and longer inference chains.

**Performance:**

- SMT2: 69% (69/100)
- JSON: 76% (76/100)

JSON outperforms SMT2 by 7% on this dataset, which is the most challenging in the suite. However, JSON's lower success rate (94% vs 99%) indicates greater difficulty in program generation.

### ProofWriter

ProofWriter tests deductive reasoning over explicit facts and rules.

**Example:**
```
Facts: "The bear is red. If something is red, then it is kind."
Question: "Is the bear kind?"
Answer: True
```

**Performance:**

- SMT2: 98.96% (95/96)
- JSON: 95.83% (92/96)

Both backends achieve high accuracy on this dataset, with SMT2 holding a slight 3% edge.

### ConditionalQA

ConditionalQA focuses on conditional reasoning with if-then statements.

**Performance:**

- SMT2: 83% (83/100)
- JSON: 76% (76/100)

SMT2 demonstrates better accuracy (+7%) and also achieves a higher success rate (100% vs 89%).

### StrategyQA

StrategyQA tests multi-hop reasoning that requires implicit world knowledge.

**Example:**
```
Question: "Would a vegetarian eat a burger made of plants?"
Answer: True (requires knowing: vegetarians avoid meat, plant burgers have no meat)
```

**Performance:**

- SMT2: 84% (84/100)
- JSON: 68% (68/100)

This dataset shows the largest performance gap, with SMT2 leading by 16%. Both backends achieve good success rates of 100% and 86% respectively.

## Analysis

### Accuracy Summary

Aggregating results across all datasets:

- **SMT2:** 86.8% average accuracy
- **JSON:** 82.8% average accuracy

SMT2 proves superior on 4 out of 5 datasets, with FOLIO being the exception where JSON leads by 7%.

### Success Rate Summary

The success rate measures program generation and execution reliability:

- **SMT2:** 99.4% average (range: 98.96-100%)
- **JSON:** 92.8% average (range: 86-100%)

SMT2 demonstrates more reliable program generation and execution overall. JSON's higher success rate variance indicates LLM generation challenges on certain datasets.

### Failure Modes

Understanding failure modes helps identify areas for improvement.

**SMT2 failures:**

- Program extraction from markdown: regex mismatch
- Z3 subprocess timeout (rare with 10s limit)
- Invalid SMT-LIB syntax (caught by Z3 parser)

**JSON failures:**

- JSON parsing errors after extraction
- Invalid sort references (e.g., undefined `Person` sort)
- Expression evaluation errors in `ExpressionParser.parse_expression()`
- Z3 Python API exceptions

## Reproducing Results

### Full benchmark suite

To run the complete benchmark suite:

```bash
python experiments_pipeline.py
```

This generates:

- `results/benchmark_results.json` - Raw metrics data
- `results/benchmark_results.md` - Formatted markdown table
- Updates `README.md` between `<!-- BENCHMARK_RESULTS_START/END -->` markers

### Single benchmark

To run just one benchmark:

```bash
python benchmark/bench_strategyqa.py
```

You'll need to modify the `BACKEND` variable in the script to either `smt2` or `json`.

### Custom evaluation

For custom evaluation on your own dataset:

```python
from utils.azure_config import get_client_config
from z3adapter.reasoning import ProofOfThought, EvaluationPipeline

config = get_client_config()
pot = ProofOfThought(llm_client=config["llm_client"], backend="smt2")
evaluator = EvaluationPipeline(proof_of_thought=pot)

result = evaluator.evaluate(
    dataset="data/strategyQA_train.json",
    max_samples=100
)

print(f"Accuracy: {result.metrics.accuracy:.2%}")
print(f"Precision: {result.metrics.precision:.4f}")
print(f"Recall: {result.metrics.recall:.4f}")
print(f"F1: {result.metrics.f1_score:.4f}")
```

## Dataset Sources

The benchmark datasets are located in the `data/` directory:

- **ProntoQA:** `data/prontoqa_test.json`
- **FOLIO:** `data/folio_test.json`
- **ProofWriter:** `data/proof_writer_test.json`
- **ConditionalQA:** `data/conditionalQA_test.json`
- **StrategyQA:** `data/strategyQA_train.json`

All datasets follow the same format: JSON arrays with `question` and `answer` fields (boolean values).

## Implementation Notes

### Parallel Processing

Benchmark scripts use `num_workers=10` with `ThreadPoolExecutor` for parallel processing. Note that `ProcessPoolExecutor` cannot be used due to ProofOfThought being unpicklable.

### Caching

Setting `skip_existing=True` enables resumption of interrupted runs. Results are cached as:

- `output/{backend}_evaluation_{dataset}/{sample_id}_result.json`
- `output/{backend}_programs_{dataset}/{sample_id}_program.{ext}`

### Timeout Handling

The `experiments_pipeline.py` script sets a 1-hour subprocess timeout for each benchmark. Individual Z3 verification calls timeout at 10 seconds, while optimization calls timeout at 100 seconds.
