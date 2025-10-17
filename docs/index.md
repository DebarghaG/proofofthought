# ProofOfThought

LLM-based reasoning using Z3 theorem proving.

## What is this?

ProofOfThought combines large language models with Z3 theorem proving to solve logical reasoning tasks. Instead of asking an LLM to "think" about a problem, we ask it to write formal logic programs that Z3 can verify.

Think of it as giving your LLM a calculator for logic.

## Quick Start

```python
from openai import OpenAI
from z3adapter.reasoning import ProofOfThought

client = OpenAI(api_key="...")
pot = ProofOfThought(llm_client=client)

result = pot.query("Would Nancy Pelosi publicly denounce abortion?")
print(result.answer)  # False
```

That's it. Three lines.

## Why use this?

**Problem:** LLMs hallucinate on logical reasoning tasks.

**Solution:** Let Z3 do the reasoning. The LLM just writes the program.

**Result:** Better accuracy on reasoning benchmarks (see [Benchmarks](benchmarks.md)).

## How it works

1. You ask a question
2. LLM generates a Z3 program (in JSON or SMT2 format)
3. Z3 proves whether the statement is satisfiable
4. You get a boolean answer

The LLM doesn't reason—it just translates natural language to formal logic. Z3 handles the reasoning.

## Features

- **Dual backends:** Choose SMT2 (standard) or JSON (easier for LLMs)
- **Azure OpenAI:** Native support for GPT-4o and GPT-5
- **Battle-tested:** Evaluated on 5 reasoning benchmarks
- **Simple API:** Three-line setup, one-line queries
- **Batch evaluation:** Built-in pipeline for dataset evaluation

## What's next?

- [Installation](installation.md) - Get set up
- [API Reference](api-reference.md) - Core usage
- [Backends](backends.md) - SMT2 vs JSON
- [Examples](examples.md) - Real code
- [Benchmarks](benchmarks.md) - Performance data
