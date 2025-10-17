# Backends

ProofOfThought supports two execution backends. Both use Z3, but they speak different languages.

## TL;DR

- **Use SMT2** (default) for standard SMT-LIB format and portability
- **Use JSON** for better LLM reliability and richer features

## SMT2 Backend

The SMT2 backend generates programs in SMT-LIB 2.0 format and runs them via the Z3 CLI.

### Example program

```smt2
(declare-sort Person 0)
(declare-const nancy Person)
(declare-fun supports_abortion (Person) Bool)
(assert (supports_abortion nancy))
(declare-const query Bool)
(assert (= query (not (supports_abortion nancy))))
(check-sat)
```

### When to use

- You want industry-standard SMT-LIB format
- You need portability to other SMT solvers
- You want standalone executable programs
- You're comfortable debugging SMT2 syntax

### Setup

```python
from z3adapter.reasoning import ProofOfThought

pot = ProofOfThought(
    llm_client=client,
    backend="smt2",      # default
    z3_path="z3"         # optional: path to Z3 executable
)
```

### Pros

✓ Standard format
✓ No Python overhead
✓ Portable to other solvers
✓ Standalone executability

### Cons

✗ Harder for LLMs to generate correctly
✗ Less structured error messages
✗ Requires Z3 CLI installed

## JSON Backend

The JSON backend uses a custom DSL that's parsed and executed via the Z3 Python API.

### Example program

```json
{
  "sorts": ["Person"],
  "constants": {
    "nancy": "Person"
  },
  "functions": [{
    "name": "supports_abortion",
    "domain": ["Person"],
    "range": "Bool"
  }],
  "knowledge_base": [
    {"type": "assert", "value": "supports_abortion(nancy)"}
  ],
  "verifications": [{
    "type": "check_sat",
    "hypotheses": ["Not(supports_abortion(nancy))"]
  }]
}
```

### When to use

- LLMs struggle with SMT2 syntax
- You want better error messages
- You don't want to install Z3 CLI
- You need richer DSL features (optimization, complex rules)

### Setup

```python
from z3adapter.reasoning import ProofOfThought

pot = ProofOfThought(
    llm_client=client,
    backend="json"
)
```

### Pros

✓ Easier for LLMs to generate
✓ Better error messages
✓ No CLI dependency
✓ Richer DSL features

### Cons

✗ Not a standard format
✗ Only works with Z3 Python API
✗ Not portable to other solvers

## How it works

### Program generation

The LLM sees different prompts for each backend:

- **SMT2**: Gets examples of SMT-LIB 2.0 programs
- **JSON**: Gets examples of the JSON DSL

Templates are in:
- `z3adapter/reasoning/smt2_prompt_template.py`
- `z3adapter/reasoning/prompt_template.py`

### Execution

Both backends return the same `VerificationResult`:

```python
@dataclass
class VerificationResult:
    answer: bool | None      # True (SAT), False (UNSAT), None (error)
    sat_count: int          # Number of SAT results
    unsat_count: int        # Number of UNSAT results
    output: str             # Raw Z3 output
    success: bool           # Did execution complete?
    error: str | None       # Error message if failed
```

### File extensions

Programs are saved with appropriate extensions:

- SMT2: `.smt2`
- JSON: `.json`

Use `save_program=True` in `query()` to keep generated programs.

## Benchmark comparison

Results on 100 samples per dataset:

| Dataset | SMT2 Accuracy | JSON Accuracy |
|---------|---------------|---------------|
| ProntoQA | 100% | 99% |
| FOLIO | 69% | 76% |
| ProofWriter | 99% | 96% |
| ConditionalQA | 83% | 76% |
| StrategyQA | 84% | 68% |

SMT2 edges out JSON on most benchmarks, but both are viable.

## Switching backends

You can compare backends on the same question:

```python
question = "Can fish breathe underwater?"

# Try both
pot_smt2 = ProofOfThought(llm_client=client, backend="smt2")
pot_json = ProofOfThought(llm_client=client, backend="json")

result_smt2 = pot_smt2.query(question)
result_json = pot_json.query(question)

print(f"SMT2: {result_smt2.answer}")
print(f"JSON: {result_json.answer}")
```

See `examples/backend_comparison.py` for a full example.

## Architecture

Both backends implement the same interface:

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
```

Location: `z3adapter/backends/`

- `abstract.py` - Interface definition
- `smt2_backend.py` - SMT-LIB 2.0 implementation
- `json_backend.py` - JSON DSL implementation

## Troubleshooting

**SMT2: "z3 command not found"**

Install Z3 CLI or switch to JSON backend.

**JSON: Slower execution?**

JSON uses Python API, which has slight overhead. Usually negligible.

**Different answers between backends?**

Both backends are correct—differences likely come from LLM generation variance. Run multiple queries or increase `max_attempts`.
