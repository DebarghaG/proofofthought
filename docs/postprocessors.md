# Postprocessing Techniques 

This page describes the postprocessing techniques available to enhance reasoning quality and reliability. All postprocessors should work seamlessly with both JSON and SMT2 backends.

## Overview

Postprocessors apply advanced prompting techniques to improve the quality of reasoning results. They work by taking an initial answer and applying various strategies to verify, refine, or enhance it.

### Available Techniques

1. **Self-Refine** - Iterative refinement through self-critique
2. **Self-Consistency** - Majority voting across multiple reasoning paths
3. **Decomposed Prompting** - Breaking complex questions into sub-questions
4. **Least-to-Most Prompting** - Progressive problem solving from simple to complex

## Quick Start

### Basic Usage

```python
from openai import OpenAI
from z3adapter.reasoning import ProofOfThought

client = OpenAI(api_key="...")

# Enable Self-Refine postprocessor
pot = ProofOfThought(
    llm_client=client,
    postprocessors=["self_refine"],
    postprocessor_configs={"self_refine": {"num_iterations": 2}}
)

result = pot.query("Your complex reasoning question here")
print(result.answer)
```

### Multiple Postprocessors

Postprocessors can be chained together:

```python
pot = ProofOfThought(
    llm_client=client,
    postprocessors=["self_refine", "self_consistency"],
    postprocessor_configs={
        "self_refine": {"num_iterations": 2},
        "self_consistency": {"num_samples": 5}
    }
)
```

### Per-Query Control

Disable postprocessing for specific queries:

```python
# Postprocessors configured but disabled for this query
result = pot.query(question, enable_postprocessing=False)
```

## Postprocessor Details

### 1. Self-Refine

**Based on:** "Self-Refine: Iterative Refinement with Self-Feedback" (Madaan et al., 2023)

**How it works:**
1. Generates initial solution
2. LLM critiques its own solution
3. Uses feedback to refine the solution
4. Repeats until convergence or max iterations

**Configuration:**
```python
postprocessor_configs={
    "self_refine": {
        "num_iterations": 2  # Number of refinement iterations (default: 2)
    }
}
```

**Best for:** Questions where the initial solution might have subtle logical errors that can be caught through self-critique.

**Example:**
```python
pot = ProofOfThought(
    llm_client=client,
    postprocessors=["self_refine"],
    postprocessor_configs={"self_refine": {"num_iterations": 3}}
)
```

### 2. Self-Consistency

**Based on:** "Self-Consistency Improves Chain of Thought Reasoning in Language Models" (Wang et al., 2022)

**How it works:**
1. Generates multiple independent reasoning paths (with higher temperature)
2. Collects answers from all paths
3. Selects most consistent answer via majority voting

**Configuration:**
```python
postprocessor_configs={
    "self_consistency": {
        "num_samples": 5  # Number of independent samples (default: 5)
    }
}
```

**Best for:** Reducing variance and improving reliability on questions where random errors might occur in single attempts.

**Example:**
```python
pot = ProofOfThought(
    llm_client=client,
    postprocessors=["self_consistency"],
    postprocessor_configs={"self_consistency": {"num_samples": 7}}
)
```

### 3. Decomposed Prompting

**Based on:** "Decomposed Prompting: A Modular Approach for Solving Complex Tasks" (Khot et al., 2022)

**How it works:**
1. Breaks complex question into simpler sub-questions
2. Solves each sub-question independently
3. Combines sub-answers to solve main question

**Configuration:**
```python
postprocessor_configs={
    "decomposed": {
        "max_subquestions": 5  # Maximum sub-questions to generate (default: 5)
    }
}
```

**Best for:** Multi-hop reasoning or questions requiring several logical steps.

**Example:**
```python
pot = ProofOfThought(
    llm_client=client,
    postprocessors=["decomposed"],
    postprocessor_configs={"decomposed": {"max_subquestions": 4}}
)
```

### 4. Least-to-Most Prompting

**Based on:** "Least-to-Most Prompting Enables Complex Reasoning in Large Language Models" (Zhou et al., 2022)

**How it works:**
1. Decomposes problem into progressive sub-problems (least to most complex)
2. Solves them sequentially
3. Uses solutions from simpler problems to inform complex ones

**Configuration:**
```python
postprocessor_configs={
    "least_to_most": {
        "max_steps": 5  # Maximum progressive steps (default: 5)
    }
}
```

**Best for:** Problems with natural dependencies where simpler sub-problems build up to the main question.

**Example:**
```python
pot = ProofOfThought(
    llm_client=client,
    postprocessors=["least_to_most"],
    postprocessor_configs={"least_to_most": {"max_steps": 4}}
)
```

## Advanced Usage

### Using Postprocessor Instances

For more control, create postprocessor instances directly:

```python
from z3adapter.postprocessors import SelfRefine, SelfConsistency

custom_refine = SelfRefine(num_iterations=3, name="CustomRefine")
custom_consistency = SelfConsistency(num_samples=10, name="CustomConsistency")

pot = ProofOfThought(
    llm_client=client,
    postprocessors=[custom_refine, custom_consistency]
)
```

### Registry Access

Query available postprocessors and their defaults:

```python
from z3adapter.postprocessors import PostprocessorRegistry

# List all available
available = PostprocessorRegistry.list_available()
print(available)  # ['self_refine', 'self_consistency', 'decomposed', 'least_to_most']

# Get default configuration
config = PostprocessorRegistry.get_default_config('self_refine')
print(config)  # {'num_iterations': 2}

# Create postprocessor
postprocessor = PostprocessorRegistry.get('self_refine', num_iterations=5)
```

### Creating Multiple Postprocessors

```python
postprocessors = PostprocessorRegistry.get_multiple(
    names=["self_refine", "self_consistency"],
    configs={
        "self_refine": {"num_iterations": 3},
        "self_consistency": {"num_samples": 7}
    }
)

pot = ProofOfThought(llm_client=client, postprocessors=postprocessors)
```

## Backend Compatibility

All postprocessors are **backend-agnostic** and work with:
- **JSON backend** (`backend="json"`)
- **SMT2 backend** (`backend="smt2"`)

Example with both backends:

```python
# JSON backend with postprocessing
pot_json = ProofOfThought(
    llm_client=client,
    backend="json",
    postprocessors=["self_refine"]
)

# SMT2 backend with postprocessing
pot_smt2 = ProofOfThought(
    llm_client=client,
    backend="smt2",
    postprocessors=["self_refine"]
)
```

## Performance Considerations

### LLM Call Costs

Postprocessors make additional LLM calls:

| Postprocessor | Additional Calls |
|---------------|------------------|
| Self-Refine | `2 * num_iterations` |
| Self-Consistency | `num_samples - 1` |
| Decomposed Prompting | `max_subquestions + 2` |
| Least-to-Most Prompting | `max_steps + 2` |



## Benchmarking with Postprocessors

You can test postprocessors on benchmarks by modifying the benchmark scripts:

```python
# In benchmark/bench_folio.py
pot = ProofOfThought(
    llm_client=config["llm_client"],
    model=config["model"],
    backend="smt2",
    postprocessors=["self_refine"],  # Add this
    postprocessor_configs={"self_refine": {"num_iterations": 2}}  # Add this
)
```

## API Reference

### ProofOfThought Parameters

```python
ProofOfThought(
    llm_client: Any,
    model: str = "gpt-5",
    backend: Literal["json", "smt2"] = "smt2",
    postprocessors: list[str] | list[Postprocessor] | None = None,
    postprocessor_configs: dict[str, dict] | None = None,
    ...
)
```

**Parameters:**
- `postprocessors`: List of postprocessor names or instances
- `postprocessor_configs`: Dictionary mapping names to configuration dicts

### Query Parameters

```python
pot.query(
    question: str,
    enable_postprocessing: bool = True,
    ...
)
```

**Parameters:**
- `enable_postprocessing`: Enable/disable postprocessing for this query

## Examples

See `examples/postprocessor_example.py` for comprehensive demonstrations of all features.

## Future Extensions

The postprocessor architecture is designed to be extensible. To add new postprocessing techniques:

1. Create a new class inheriting from `Postprocessor`
2. Implement the `process()` method
3. Register in `PostprocessorRegistry._POSTPROCESSOR_MAP`

See `z3adapter/postprocessors/abstract.py` for the base interface.
