# ProofOfThought

ProofOfThought provides LLM-guided translation of natural language questions into formal logic, which is then verified using the Z3 theorem prover.

## Architecture

The system follows a multi-stage pipeline to transform questions into verifiable answers:

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

The architecture consists of several key components that work together:

**Z3ProgramGenerator** (`z3adapter.reasoning.program_generator`)
Provides the LLM interface for program generation. It extracts formal programs from markdown code blocks using regex and supports error feedback through multi-turn conversations.

**Backend** (`z3adapter.backends.abstract`)
Defines an abstract interface with `execute(program_path) → VerificationResult`. Two concrete implementations are available:

- **SMT2Backend**: Subprocess call to Z3 CLI. Parses stdout/stderr for `sat`/`unsat` via regex `(?<!un)\bsat\b` and `\bunsat\b`.
- **JSONBackend**: Python API execution via `Z3JSONInterpreter`. Returns structured SAT/UNSAT counts.

**Z3JSONInterpreter** (`z3adapter.interpreter`)
Implements a multi-stage pipeline for processing the JSON DSL:

1. **SortManager**: Performs topological sorting of type dependencies and creates Z3 sorts
2. **ExpressionParser**: Evaluates expressions using `eval()` with restricted globals for security
3. **Verifier**: Runs `solver.check(condition)` for each verification
4. Finally returns SAT/UNSAT counts

**ProofOfThought** (`z3adapter.reasoning.proof_of_thought`)
Provides the high-level API with a retry loop (default `max_attempts=3`) and error feedback. Answer determination follows: `SAT only → True`, `UNSAT only → False`, `both/neither → None`.

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

ProofOfThought has been evaluated on multiple reasoning datasets using the following configuration:

- **Datasets**: ProntoQA, FOLIO, ProofWriter, ConditionalQA, StrategyQA
- **Model**: GPT-5 (Azure deployment)
- **Config**: `max_attempts=3`, `verify_timeout=10000ms`

| Backend | Avg Accuracy | Success Rate |
|---------|--------------|--------------|
| SMT2 | 86.8% | 99.4% |
| JSON | 82.8% | 92.8% |

The SMT2 backend outperforms JSON on 4 out of 5 datasets. For detailed results, see [Benchmarks](benchmarks.md).

## Design Rationale

Several key design decisions shape the architecture:

- **Why use an external theorem prover?** LLMs lack deductive closure, meaning they cannot guarantee sound logical inference. Z3 provides this soundness by formally verifying the logical reasoning.

- **Why offer two backends?** The choice trades off portability (SMT-LIB is a widely-supported standard) against LLM generation reliability (structured JSON is easier for models to produce correctly).

- **Why use iterative refinement?** Single-shot generation is often insufficient for complex reasoning. By incorporating error feedback, the system significantly improves its success rate.

## Implementation Notes

Each backend has distinct implementation characteristics:

**SMT2 Backend:**

- Runs Z3 as a subprocess with the `-T:timeout` flag
- Parses output using regex patterns on stdout/stderr
- Uses standard SMT-LIB 2.0 S-expressions

**JSON Backend:**

- Leverages the Python Z3 API through the `z3-solver` package
- Evaluates expressions using restricted `eval()` with `ExpressionValidator`
- Supports built-in sorts: `BoolSort`, `IntSort`, `RealSort`
- Supports custom sorts: `DeclareSort`, `EnumSort`, `BitVecSort`, `ArraySort`
- Handles quantifiers: `ForAll` and `Exists` with proper variable binding

**Security:**

The JSON backend employs `ExpressionValidator.safe_eval()` with a whitelist of allowed Z3 operators, preventing arbitrary code execution.

For more details, see [Backends](backends.md) and [API Reference](api-reference.md).
