# Benchmarks

Evaluation on 5 logical reasoning datasets using Azure GPT-5.

## Methodology

**Model:** Azure GPT-5 deployment
**Configuration:**
- `max_attempts=3` (retry with error feedback)
- `verify_timeout=10000ms`
- `optimize_timeout=100000ms` (JSON backend only)
- `num_workers=10` (ThreadPoolExecutor for parallel processing)

**Metrics:** `sklearn.metrics`
- Accuracy: `accuracy_score(y_true, y_pred)`
- Precision: `precision_score(y_true, y_pred, zero_division=0)`
- Recall: `recall_score(y_true, y_pred, zero_division=0)`
- F1: `2 * (precision * recall) / (precision + recall)`
- Success Rate: `(total - failed) / total`

**Execution:** `experiments_pipeline.py` runs all benchmarks sequentially, modifying `BACKEND` variable in each `benchmark/bench_*.py` script via regex substitution.

## Results

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

### ProntoQA

Synthetic first-order logic with deterministic inference.

**Example:**
```
Facts: "Stella is a lion. All lions are brown."
Question: "Is Stella brown?"
Answer: True
```

**Performance:**
- SMT2: 100% (100/100)
- JSON: 99% (99/100)

Both backends near-perfect. Simplest dataset.

### FOLIO

First-order logic from Wikipedia articles.

**Characteristics:** Complex nested quantifiers, longer inference chains.

**Performance:**
- SMT2: 69% (69/100)
- JSON: 76% (76/100)

JSON outperforms SMT2 (+7%). Most challenging dataset. Lower success rate for JSON (94% vs 99%) indicates generation difficulties.

### ProofWriter

Deductive reasoning over explicit facts and rules.

**Example:**
```
Facts: "The bear is red. If something is red, then it is kind."
Question: "Is the bear kind?"
Answer: True
```

**Performance:**
- SMT2: 98.96% (95/96)
- JSON: 95.83% (92/96)

High accuracy for both. SMT2 slight edge (+3%).

### ConditionalQA

Conditional reasoning with if-then statements.

**Performance:**
- SMT2: 83% (83/100)
- JSON: 76% (76/100)

SMT2 better accuracy (+7%) and higher success rate (100% vs 89%).

### StrategyQA

Multi-hop reasoning requiring implicit world knowledge.

**Example:**
```
Question: "Would a vegetarian eat a burger made of plants?"
Answer: True (requires knowing: vegetarians avoid meat, plant burgers have no meat)
```

**Performance:**
- SMT2: 84% (84/100)
- JSON: 68% (68/100)

Largest gap (+16% for SMT2). Both achieve 100%/86% success rates respectively.

## Analysis

### Accuracy Summary

**SMT2:** 86.8% average across datasets
**JSON:** 82.8% average across datasets

SMT2 superior on 4/5 datasets (FOLIO exception where JSON +7%).

### Success Rate Summary

**SMT2:** 99.4% average (range: 98.96-100%)
**JSON:** 92.8% average (range: 86-100%)

SMT2 more reliable program generation and execution. JSON success rate variance higher, indicating LLM generation issues on some datasets.

### Failure Modes

**SMT2 failures:**
- JSON extraction from markdown: regex mismatch
- Z3 subprocess timeout (rare with 10s limit)
- Invalid SMT-LIB syntax (caught by Z3 parser)

**JSON failures:**
- JSON parsing errors post-extraction
- Invalid sort references (e.g., undefined `Person` sort)
- Expression evaluation errors in `ExpressionParser.parse_expression()`
- Z3 Python API exceptions

## Reproducing Results

### Full benchmark suite

```bash
python experiments_pipeline.py
```

Generates:
- `results/benchmark_results.json` - Raw metrics
- `results/benchmark_results.md` - Markdown table
- Updates `README.md` between `<!-- BENCHMARK_RESULTS_START/END -->` markers

### Single benchmark

```bash
python benchmark/bench_strategyqa.py
```

Modify `BACKEND` variable in script (`smt2` or `json`).

### Custom evaluation

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

- **ProntoQA:** `data/prontoqa_test.json`
- **FOLIO:** `data/folio_test.json`
- **ProofWriter:** `data/proof_writer_test.json`
- **ConditionalQA:** `data/conditionalQA_test.json`
- **StrategyQA:** `data/strategyQA_train.json`

Format: JSON arrays with `question` and `answer` fields (boolean).

## Implementation Notes

**Parallel Processing:**
Benchmark scripts use `num_workers=10` with `ThreadPoolExecutor` (not `ProcessPoolExecutor` due to ProofOfThought unpicklability).

**Caching:**
`skip_existing=True` enables resumption. Results cached as:
- `output/{backend}_evaluation_{dataset}/{sample_id}_result.json`
- `output/{backend}_programs_{dataset}/{sample_id}_program.{ext}`

**Timeout Handling:**
`experiments_pipeline.py` sets 1-hour subprocess timeout per benchmark. Individual Z3 calls timeout at 10s (verify) or 100s (optimize).
