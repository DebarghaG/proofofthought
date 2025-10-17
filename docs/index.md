# ProofOfThought

LLM-guided translation of natural language to formal logic, verified via Z3 theorem prover.

## Architecture

```
Question (NL)
    ↓
LLM Translation (few-shot prompting)
    ↓
Formal Program (SMT-LIB 2.0 or JSON DSL)
    ↓
Z3 Execution
    ↓
SAT/UNSAT → Boolean Answer
```

### Components

**Z3ProgramGenerator** (`z3adapter.reasoning.program_generator`)
LLM interface for program generation. Extracts formal programs from markdown code blocks using regex. Supports error feedback via multi-turn conversations.

**Backend** (`z3adapter.backends.abstract`)
Abstract interface: `execute(program_path) → VerificationResult`. Concrete implementations:

- **SMT2Backend**: Subprocess call to Z3 CLI. Parses stdout/stderr for `sat`/`unsat` via regex `(?<!un)\bsat\b` and `\bunsat\b`.
- **JSONBackend**: Python API execution via `Z3JSONInterpreter`. Returns structured SAT/UNSAT counts.

**Z3JSONInterpreter** (`z3adapter.interpreter`)
Multi-stage pipeline for JSON DSL:

1. SortManager: Topological sort of type dependencies, create Z3 sorts
2. ExpressionParser: `eval()` with restricted globals for safety
3. Verifier: `solver.check(condition)` for each verification
4. Return SAT/UNSAT counts

**ProofOfThought** (`z3adapter.reasoning.proof_of_thought`)
High-level API. Retry loop (default `max_attempts=3`) with error feedback. Answer determination: `SAT only → True`, `UNSAT only → False`, `both/neither → None`.

## Quick Start

```python
from openai import OpenAI
from z3adapter.reasoning import ProofOfThought

client = OpenAI(api_key="...")
pot = ProofOfThought(llm_client=client, backend="smt2")
result = pot.query("Would Nancy Pelosi publicly denounce abortion?")
# result.answer: False (UNSAT)
```

## Benchmark Results

Datasets: ProntoQA, FOLIO, ProofWriter, ConditionalQA, StrategyQA
Model: GPT-5 (Azure deployment)
Config: `max_attempts=3`, `verify_timeout=10000ms`

| Backend | Avg Accuracy | Success Rate |
|---------|--------------|--------------|
| SMT2 | 86.8% | 99.4% |
| JSON | 82.8% | 92.8% |

SMT2 outperforms JSON on 4/5 datasets. Full results: [Benchmarks](benchmarks.md)

## Design Rationale

**Why external theorem prover?**
LLMs lack deductive closure. Z3 provides sound logical inference.

**Why two backends?**
Trade portability (SMT-LIB standard) vs LLM generation reliability (structured JSON).

**Why iterative refinement?**
Single-shot generation insufficient. Error feedback improves success rate.

## Implementation Notes

**SMT2 Backend**
- Z3 subprocess with `-T:timeout` flag
- Output parsing: regex on stdout/stderr
- Standard SMT-LIB 2.0 S-expressions

**JSON Backend**
- Python Z3 API via `z3-solver` package
- Expression evaluation: restricted `eval()` with `ExpressionValidator`
- Supports built-in sorts: `BoolSort`, `IntSort`, `RealSort`
- Custom sorts: `DeclareSort`, `EnumSort`, `BitVecSort`, `ArraySort`
- Quantifiers: `ForAll`, `Exists` with variable binding

**Security**
JSON backend uses `ExpressionValidator.safe_eval()` with whitelisted Z3 operators. No arbitrary code execution.

See: [Backends](backends.md), [API Reference](api-reference.md)
