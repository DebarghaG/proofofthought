# Backends

Two execution backends for Z3: SMT-LIB 2.0 (standard) and JSON DSL (custom).

## SMT2Backend

**Implementation:** `z3adapter/backends/smt2_backend.py`

### Execution

```python
subprocess.run([z3_path, f"-T:{timeout_seconds}", program_path])
```

- Z3 CLI subprocess with timeout flag
- Hard timeout: `timeout_seconds + 10`
- Output captured from stdout + stderr

### Result Parsing

```python
sat_pattern = r"(?<!un)\bsat\b"      # Negative lookbehind to exclude "unsat"
unsat_pattern = r"\bunsat\b"
```

Counts occurrences in Z3 output. Answer logic:
- `sat_count > 0, unsat_count == 0` → `True`
- `unsat_count > 0, sat_count == 0` → `False`
- Otherwise → `None`

### Prompt Template

Source: `z3adapter/reasoning/smt2_prompt_template.py`

Instructions for generating SMT-LIB 2.0 programs. Key requirements:
- All commands as S-expressions: `(command args...)`
- Declare sorts before use
- Single `(check-sat)` per program
- Semantic: `sat` = constraint satisfiable, `unsat` = contradicts knowledge base

### File Extension

`.smt2`

##JSON Backend

**Implementation:** `z3adapter/backends/json_backend.py`

### Execution Pipeline

```python
interpreter = Z3JSONInterpreter(program_path, verify_timeout, optimize_timeout)
interpreter.run()
sat_count, unsat_count = interpreter.get_verification_counts()
```

### Z3JSONInterpreter Pipeline

**Step 1: SortManager** (`z3adapter/dsl/sorts.py`)

Topologically sorts type definitions to handle dependencies. Creates Z3 sorts:

- Built-in: `BoolSort()`, `IntSort()`, `RealSort()` (pre-defined)
- Custom: `DeclareSort(name)`, `EnumSort(name, values)`, `BitVecSort(n)`, `ArraySort(domain, range)`

Example ArraySort dependency:
```json
{"name": "IntArray", "type": "ArraySort(IntSort, IntSort)"}
```

Requires `IntSort` already defined (built-in) before creating `IntArray`.

**Step 2: ExpressionParser** (`z3adapter/dsl/expressions.py`)

Parses logical expressions from strings via restricted `eval()`:

```python
safe_globals = {**Z3_OPERATORS, **functions}
context = {**functions, **constants, **variables, **quantified_vars}
ExpressionValidator.safe_eval(expr_str, safe_globals, context)
```

Whitelisted operators:
```python
Z3_OPERATORS = {
    "And", "Or", "Not", "Implies", "If", "Distinct",
    "Sum", "Product", "ForAll", "Exists", "Function", "Array", "BitVecVal"
}
```

**Step 3: Verifier** (`z3adapter/verification/verifier.py`)

For each verification condition:
```python
result = solver.check(condition)  # Adds condition as hypothesis to KB
if result == sat:
    sat_count += 1
elif result == unsat:
    unsat_count += 1
```

**Verification Semantics:**
- `solver.check(φ)` asks: "Is KB ∧ φ satisfiable?"
- SAT: φ is consistent with KB (possible)
- UNSAT: φ contradicts KB (impossible)

### Prompt Template

Source: `z3adapter/reasoning/prompt_template.py`

Comprehensive 546-line specification of JSON DSL. Key sections:

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
Three types:

1. Simple constraint:
```json
{"name": "test", "constraint": "supports_abortion(nancy)"}
```

2. Existential:
```json
{"name": "test", "exists": [{"name": "x", "sort": "Int"}], "constraint": "x > 0"}
```

3. Universal:
```json
{"name": "test", "forall": [{"name": "x", "sort": "Int"}],
 "implies": {"antecedent": "x > 0", "consequent": "x >= 1"}}
```

**Critical constraint:** Single verification per question (avoid ambiguous results from testing both φ and ¬φ).

### File Extension

`.json`

## Benchmark Performance

Results from `experiments_pipeline.py` (100 samples per dataset, GPT-5, `max_attempts=3`):

| Dataset | SMT2 Accuracy | JSON Accuracy | SMT2 Success | JSON Success |
|---------|---------------|---------------|--------------|--------------|
| ProntoQA | 100% | 99% | 100% | 100% |
| FOLIO | 69% | 76% | 99% | 94% |
| ProofWriter | 99% | 96% | 99% | 96% |
| ConditionalQA | 83% | 76% | 100% | 89% |
| StrategyQA | 84% | 68% | 100% | 86% |

**Success Rate** = percentage of queries completing without error (generation + execution).

SMT2 higher accuracy on 4/5 datasets. JSON higher success rate variance (86-100% vs 99-100%).

## Implementation Differences

### Program Generation

**SMT2:** Extract from markdown via:
```python
pattern = r"```smt2\s*([\s\S]*?)\s*```"
```

**JSON:** Extract and parse via:
```python
pattern = r"```json\s*(\{[\s\S]*?\})\s*```"
json.loads(match.group(1))
```

### Error Handling

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

**SMT2:**
- Single timeout parameter: `verify_timeout` (ms)
- Converted to seconds for Z3 CLI: `verify_timeout // 1000`
- Hard subprocess timeout: `timeout_seconds + 10`

**JSON:**
- Two timeouts: `verify_timeout` (ms), `optimize_timeout` (ms)
- Set via `solver.set("timeout", verify_timeout)` in Verifier
- Applies per `solver.check()` call

## Backend Selection Code

```python
if backend == "json":
    from z3adapter.backends.json_backend import JSONBackend
    backend_instance = JSONBackend(verify_timeout, optimize_timeout)
else:  # smt2
    from z3adapter.backends.smt2_backend import SMT2Backend
    backend_instance = SMT2Backend(verify_timeout, z3_path)
```

File: `z3adapter/reasoning/proof_of_thought.py:78-90`

## Prompt Selection

```python
if self.backend == "json":
    prompt = build_prompt(question)
else:  # smt2
    prompt = build_smt2_prompt(question)
```

File: `z3adapter/reasoning/program_generator.py:78-81`

Prompts include few-shot examples and format specifications. SMT2 prompt emphasizes S-expression syntax. JSON prompt details variable scoping and quantifier semantics.
