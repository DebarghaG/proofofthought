# Benchmarks

ProofOfThought has been evaluated on 5 logical reasoning datasets.

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

## Datasets

### ProntoQA

Synthetic first-order logic problems with clear provable answers.

**Example:**

```
Question: "Stella is a lion. All lions are brown. Is Stella brown?"
Answer: True
```

**Performance:** Near-perfect accuracy with both backends. This is the easiest dataset.

### FOLIO

First-order logic inference problems derived from Wikipedia.

**Example:**

```
Question: "All cats are mammals. Fluffy is a cat. Is Fluffy a mammal?"
Answer: True
```

**Performance:** Most challenging dataset. SMT2 gets 69%, JSON gets 76%. The higher accuracy with JSON suggests LLMs struggle with SMT2 syntax for complex logic.

### ProofWriter

Deductive reasoning over facts and rules.

**Example:**

```
Facts: "The bear is red. If something is red, then it is kind."
Question: "Is the bear kind?"
Answer: True
```

**Performance:** Near-perfect with SMT2 (99%), very good with JSON (96%).

### ConditionalQA

Reasoning with conditional statements.

**Example:**

```
Question: "If it rains, the ground is wet. It is raining. Is the ground wet?"
Answer: True
```

**Performance:** SMT2 achieves 83%, JSON achieves 76%. Both backends handle conditionals well.

### StrategyQA

Multi-hop reasoning requiring implicit knowledge.

**Example:**

```
Question: "Would a vegetarian eat a burger made of plants?"
Answer: True
```

**Performance:** SMT2 gets 84%, JSON gets 68%. This dataset requires more complex reasoning chains.

## Metrics Explained

- **Accuracy**: Percentage of correct predictions
- **Precision**: Of all positive predictions, how many were correct?
  - `True Positives / (True Positives + False Positives)`
- **Recall**: Of all actual positives, how many did we catch?
  - `True Positives / (True Positives + False Negatives)`
- **F1 Score**: Harmonic mean of precision and recall
  - `2 × (Precision × Recall) / (Precision + Recall)`
- **Success Rate**: Percentage of queries that completed without errors

## Backend Comparison

### SMT2 Backend

**Strengths:**
- Better on ProofWriter (99% vs 96%)
- Better on ConditionalQA (83% vs 76%)
- Better on StrategyQA (84% vs 68%)
- Higher overall accuracy on 4/5 benchmarks

**Weaknesses:**
- Slightly worse on FOLIO (69% vs 76%)
- More generation errors (lower success rate on some datasets)

### JSON Backend

**Strengths:**
- Better on FOLIO (76% vs 69%)
- More reliable generation (higher success rates)
- Better error messages for debugging

**Weaknesses:**
- Lower accuracy on StrategyQA (68% vs 84%)
- Lower accuracy on ConditionalQA (76% vs 83%)

## Running Your Own Benchmarks

### Full suite

```bash
python experiments_pipeline.py
```

This runs all 5 benchmarks with both backends and updates the README.

### Single benchmark

```python
from utils.azure_config import get_client_config
from z3adapter.reasoning import ProofOfThought, EvaluationPipeline

config = get_client_config()

pot = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="smt2"
)

evaluator = EvaluationPipeline(proof_of_thought=pot)

result = evaluator.evaluate(
    dataset="data/strategyQA_train.json",
    max_samples=100
)

print(f"Accuracy: {result.metrics.accuracy:.2%}")
```

### Custom datasets

See [Examples](examples.md#dataset-format) for dataset format requirements.

## Performance Notes

**Generation time:** 2-5 seconds per query on average with GPT-5.

**Success rate:** SMT2 achieves 99-100% success rate. JSON achieves 86-100% success rate.

**Timeouts:** Default timeouts (10s verify, 100s optimize) work well for these datasets.

## Why the differences?

Backend performance varies because:

1. **LLM generation reliability**: JSON is more structured, easier for LLMs to generate correctly
2. **Syntax complexity**: SMT2 requires precise S-expression syntax
3. **Error recovery**: JSON provides better error messages, leading to better retries
4. **Dataset characteristics**: Some logical patterns are easier in one DSL vs the other

**Recommendation:** Start with SMT2 (default). Switch to JSON if you see low success rates.

## Reproducing Results

All results are from:

- **Model:** GPT-5 (Azure deployment)
- **Max attempts:** 3
- **Verify timeout:** 10000ms
- **Optimize timeout:** 100000ms
- **Sample size:** 100 per dataset (96 for ProofWriter)

To reproduce:

```bash
# Set up Azure config in .env
# Then run experiments
python experiments_pipeline.py
```

Results are saved to `results/` with timestamp and full metrics.
