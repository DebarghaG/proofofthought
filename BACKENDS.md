# Backend System

ProofOfThought now supports multiple execution backends for Z3 theorem proving.

## Available Backends

### 1. SMT2 Backend (Default)

The SMT2 backend generates programs in SMT-LIB 2.0 format and executes them via the Z3 command-line interface.

**Advantages:**
- Standard SMT-LIB 2.0 format (portable to other solvers)
- Direct Z3 CLI execution (no Python interpreter overhead)
- Programs can be run standalone with `z3 program.smt2`

**Usage:**
```python
from z3dsl.reasoning import ProofOfThought

pot = ProofOfThought(
    llm_client=client,
    backend="smt2",  # default
    z3_path="z3"  # optional: specify Z3 executable path
)
result = pot.query("Can fish breathe underwater?")
```

### 2. JSON Backend

The JSON backend uses a custom JSON DSL that is parsed by Python and executed via the Z3 Python API.

**Advantages:**
- More structured and easier for LLMs to generate correctly
- Better error messages and debugging
- Richer DSL features (optimization, complex rules)

**Usage:**
```python
from z3dsl.reasoning import ProofOfThought

pot = ProofOfThought(
    llm_client=client,
    backend="json"
)
result = pot.query("Can fish breathe underwater?")
```

## How It Works

1. **Program Generation**: The LLM generates programs in the format specified by the backend
   - JSON backend: Uses `z3dsl.reasoning.prompt_template`
   - SMT2 backend: Uses `z3dsl.reasoning.smt2_prompt_template`

2. **Execution**: Programs are saved to temporary files and executed
   - JSON backend: Parsed and executed via `z3dsl.interpreter.Z3JSONInterpreter`
   - SMT2 backend: Executed via Z3 CLI subprocess

3. **Result Parsing**: Both backends return a `VerificationResult` with:
   - `answer`: `True` (SAT), `False` (UNSAT), or `None` (ambiguous/error)
   - `sat_count`: Number of SAT results
   - `unsat_count`: Number of UNSAT results
   - `output`: Raw execution output

## Backend Selection

Choose your backend based on your needs:

- **Use SMT2** (default) if you want:
  - Standard SMT-LIB 2.0 format
  - Portability to other SMT solvers
  - Standalone executable programs

- **Use JSON** if you want:
  - Better LLM generation reliability
  - Richer DSL features
  - Better debugging and error messages

## Example: Comparing Backends

```python
from azure_config import get_client_config
from z3dsl.reasoning import ProofOfThought

config = get_client_config()
question = "Can fish breathe underwater?"

# JSON backend
pot_json = ProofOfThought(llm_client=config["llm_client"], backend="json")
result_json = pot_json.query(question)

# SMT2 backend
pot_smt2 = ProofOfThought(llm_client=config["llm_client"], backend="smt2")
result_smt2 = pot_smt2.query(question)

print(f"JSON answer: {result_json.answer}")
print(f"SMT2 answer: {result_smt2.answer}")
```

See `examples/backend_comparison.py` for a complete example.

## File Extensions

- JSON programs: `.json`
- SMT2 programs: `.smt2`

Programs can be saved using `save_program=True` in the `query()` method.

## Architecture

The backend system follows an abstract interface pattern:

```
z3dsl/backends/
├── abstract.py         # Backend interface
├── json_backend.py     # JSON DSL backend
└── smt2_backend.py     # SMT-LIB 2.0 backend
```

Each backend implements:
- `execute(program_path)`: Run a program and return results
- `get_file_extension()`: Get the file extension (.json or .smt2)
- `get_prompt_template()`: Get the LLM prompt for program generation
