# Backends

ProofOfThought supports two execution backends for Z3: the standard SMT-LIB 2.0 format and a custom JSON DSL.

## SMT2Backend

The SMT2 backend leverages Z3's standard command-line interface.

**Implementation:** `z3adapter/backends/smt2_backend.py`

### Execution

```python
subprocess.run([z3_path, f"-T:{timeout_seconds}", program_path])
```

The execution process involves:

- Running Z3 as a CLI subprocess with a timeout flag
- Applying a hard timeout of `timeout_seconds + 10` to prevent hanging
- Capturing output from both stdout and stderr

### Result Parsing

```python
sat_pattern = r"(?<!un)\bsat\b"      # Negative lookbehind to exclude "unsat"
unsat_pattern = r"\bunsat\b"
```

The parser counts occurrences in Z3 output and applies the following answer logic:

- `sat_count > 0, unsat_count == 0` → `True`
- `unsat_count > 0, sat_count == 0` → `False`
- Otherwise → `None`

### Prompt Template

The prompt template guides LLM program generation.

**Source:** `z3adapter/reasoning/smt2_prompt_template.py`

The template provides instructions for generating SMT-LIB 2.0 programs with these key requirements:
- All commands as S-expressions: `(command args...)`
- Declare sorts before use
- Single `(check-sat)` per program
- Semantic: `sat` = constraint satisfiable, `unsat` = contradicts knowledge base

### File Extension

`.smt2`

## JSON Backend

The JSON backend uses Z3's Python API for direct programmatic access.

**Implementation:** `z3adapter/backends/json_backend.py`

### Execution Pipeline

```python
interpreter = Z3JSONInterpreter(program_path, verify_timeout, optimize_timeout)
interpreter.run()
sat_count, unsat_count = interpreter.get_verification_counts()
```

### Z3JSONInterpreter Pipeline

The interpreter processes JSON programs through three main stages:

**Step 1: SortManager** (`z3adapter/dsl/sorts.py`)

First, the system topologically sorts type definitions to handle dependencies, then creates Z3 sorts:

- Built-in: `BoolSort()`, `IntSort()`, `RealSort()` (pre-defined)
- Custom: `DeclareSort(name)`, `EnumSort(name, values)`, `BitVecSort(n)`, `ArraySort(domain, range)`

For example, an ArraySort creates dependencies:
```json
{"name": "IntArray", "type": "ArraySort(IntSort, IntSort)"}
```

This requires `IntSort` to be defined first (fortunately, it's built-in) before creating `IntArray`.

**Step 2: ExpressionParser** (`z3adapter/dsl/expressions.py`)

Next, the parser evaluates logical expressions from strings using a restricted `eval()`:

```python
safe_globals = {**Z3_OPERATORS, **functions}
context = {**functions, **constants, **variables, **quantified_vars}
ExpressionValidator.safe_eval(expr_str, safe_globals, context)
```

Only whitelisted operators are permitted:
```python
Z3_OPERATORS = {
    "And", "Or", "Not", "Implies", "If", "Distinct",
    "Sum", "Product", "ForAll", "Exists", "Function", "Array", "BitVecVal"
}
```

**Step 3: Verifier** (`z3adapter/verification/verifier.py`)

Finally, the verifier tests each verification condition:
```python
result = solver.check(condition)  # Adds condition as hypothesis to KB
if result == sat:
    sat_count += 1
elif result == unsat:
    unsat_count += 1
```

**Verification Semantics:**
When calling `solver.check(φ)`, the system asks: "Is KB ∧ φ satisfiable?"

- **SAT**: φ is consistent with the knowledge base (possible scenario)
- **UNSAT**: φ contradicts the knowledge base (impossible scenario)

### Prompt Template

The JSON prompt template is more comprehensive than its SMT2 counterpart.

**Source:** `z3adapter/reasoning/prompt_template.py`

This 546-line specification of the JSON DSL includes these key sections:

**Sorts:**
```json
{"name": "Person", "type": "DeclareSort"}
```

**Functions:**
```json
{"name": "supports", "domain": ["Person", "Issue"], "range": "BoolSort"}
```

**Constants:**
```json
{"persons": {"sort": "Person", "members": ["nancy_pelosi"]}}
```

**Variables:**
Free variables for quantifier binding:
```json
{"name": "p", "sort": "Person"}
```

**Knowledge Base:**
```json
["ForAll([p], Implies(is_democrat(p), supports_abortion(p)))"]
```

**Verifications:**
The DSL supports three types of verifications:

1. **Simple constraint:**
```json
{"name": "test", "constraint": "supports_abortion(nancy)"}
```

2. **Existential:**
```json
{"name": "test", "exists": [{"name": "x", "sort": "Int"}], "constraint": "x > 0"}
```

3. **Universal:**
```json
{"name": "test", "forall": [{"name": "x", "sort": "Int"}],
 "implies": {"antecedent": "x > 0", "consequent": "x >= 1"}}
```

**Critical constraint:** The prompt enforces a single verification per question to avoid ambiguous results from testing both φ and ¬φ.

### File Extension

`.json`

## Benchmark Performance

Performance comparison across datasets reveals notable differences between the backends.

**Results from** `experiments_pipeline.py` (100 samples per dataset, GPT-5, `max_attempts=3`):

| Dataset | SMT2 Accuracy | JSON Accuracy | SMT2 Success | JSON Success |
|---------|---------------|---------------|--------------|--------------|
| ProntoQA | 100% | 99% | 100% | 100% |
| FOLIO | 69% | 76% | 99% | 94% |
| ProofWriter | 99% | 96% | 99% | 96% |
| ConditionalQA | 83% | 76% | 100% | 89% |
| StrategyQA | 84% | 68% | 100% | 86% |

**Success Rate** represents the percentage of queries that complete without error (including both generation and execution).

Overall, SMT2 achieves higher accuracy on 4 out of 5 datasets, while JSON shows greater success rate variance (86-100% compared to SMT2's 99-100%).

## Implementation Differences

The backends differ in several implementation details.

### Program Generation

**SMT2:** Extracts programs from markdown via:
```python
pattern = r"```smt2\s*([\s\S]*?)\s*```"
```

**JSON:** Extracts and parses via:
```python
pattern = r"```json\s*(\{[\s\S]*?\})\s*```"
json.loads(match.group(1))
```

### Error Handling

Error handling varies significantly between backends.

**SMT2:**
- Subprocess timeout → `TimeoutExpired`
- Parse errors → regex mismatch → `answer=None`
- Z3 errors in stderr → still parsed

**JSON:**
- JSON parse error → extraction failure
- Z3 Python API exception → caught in `try/except`
- Invalid sort reference → `ValueError` during SortManager
- Expression eval error → `ValueError` during ExpressionParser

### Timeout Configuration

Timeout handling differs between the two backends.

**SMT2:**
- Uses a single timeout parameter: `verify_timeout` (ms)
- Converts to seconds for Z3 CLI: `verify_timeout // 1000`
- Applies a hard subprocess timeout: `timeout_seconds + 10`

**JSON:**
- Uses two separate timeouts: `verify_timeout` (ms) and `optimize_timeout` (ms)
- Sets timeout via `solver.set("timeout", verify_timeout)` in Verifier
- Timeout applies per individual `solver.check()` call

## Backend Selection Code

The system selects backends at runtime based on configuration:

```python
if backend == "json":
    from z3adapter.backends.json_backend import JSONBackend
    backend_instance = JSONBackend(verify_timeout, optimize_timeout)
else:  # smt2
    from z3adapter.backends.smt2_backend import SMT2Backend
    backend_instance = SMT2Backend(verify_timeout, z3_path)
```

**File:** `z3adapter/reasoning/proof_of_thought.py:78-90`

## Prompt Selection

The appropriate prompt template is chosen based on the selected backend:

```python
if self.backend == "json":
    prompt = build_prompt(question)
else:  # smt2
    prompt = build_smt2_prompt(question)
```

**File:** `z3adapter/reasoning/program_generator.py:78-81`

Both prompts include few-shot examples and format specifications. The SMT2 prompt emphasizes S-expression syntax, while the JSON prompt provides detailed guidance on variable scoping and quantifier semantics.
