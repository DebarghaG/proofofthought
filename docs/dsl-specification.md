# DSL Specification

Technical details of the JSON DSL implementation.

## Rules vs Verifications

**Critical distinction:** Rules modify the solver state. Verifications query the solver state.

### Rules

**Implementation:** `z3adapter/dsl/expressions.py:159-204`

**Operation:** `solver.add(assertion)`

Rules are **permanently asserted** into the solver's knowledge base during step 6 of interpretation.

```python
# Line 189: Implication rule
solver.add(ForAll(variables, Implies(antecedent, consequent)))

# Line 194-196: Constraint rule
if variables:
    solver.add(ForAll(variables, constraint))
else:
    solver.add(constraint)
```

**Structure:**
```json
{
  "forall": [{"name": "p", "sort": "Person"}],
  "implies": {
    "antecedent": "is_democrat(p)",
    "consequent": "supports_abortion(p)"
  }
}
```

**Effect:** Defines axioms. Every subsequent verification will inherit this constraint.

### Verifications

**Implementation:** `z3adapter/verification/verifier.py:84-127`

**Operation:** `solver.check(condition)`

Verifications **test conditions** against the existing knowledge base without modifying it.

```python
# Line 113
result = solver.check(condition)  # Temporary hypothesis check

if result == sat:
    self.sat_count += 1
elif result == unsat:
    self.unsat_count += 1
```

**Semantics:** Checks if `KB ∧ condition` is satisfiable.

- **SAT**: condition is consistent with KB
- **UNSAT**: condition contradicts KB

**Structure:**
```json
{
  "name": "test_pelosi",
  "constraint": "publicly_denounce(nancy, abortion)"
}
```

**Effect:** Returns SAT/UNSAT but does NOT add to KB.

### Example

```json
{
  "rules": [
    {
      "forall": [{"name": "p", "sort": "Person"}],
      "implies": {"antecedent": "is_democrat(p)", "consequent": "supports_abortion(p)"}
    }
  ],
  "knowledge_base": ["is_democrat(nancy)"],
  "verifications": [
    {"name": "test", "constraint": "supports_abortion(nancy)"}
  ]
}
```

**Execution:**
1. `solver.add(ForAll([p], Implies(is_democrat(p), supports_abortion(p))))` — rule
2. `solver.add(is_democrat(nancy))` — knowledge base
3. `solver.check(supports_abortion(nancy))` — verification → **SAT**

## Variable Scoping

**Implementation:** `z3adapter/dsl/expressions.py:69-107`

### Free Variables

Declared in global `"variables"` section. Available throughout program.

```json
"variables": [{"name": "x", "sort": "Int"}]
```

Added to evaluation context (line 91):
```python
context.update(self.variables)
```

### Quantified Variables

Bound by `ForAll` or `Exists` quantifiers. Temporarily shadow free variables within quantified scope.

```json
"knowledge_base": ["ForAll([x], x > 0)"]
```

Here `x` must exist in context (from `"variables"`) to be bound by `ForAll`.

### Shadowing

Code checks for shadowing (lines 100-106):
```python
for v in quantified_vars:
    var_name = v.decl().name()
    if var_name in context and var_name not in [...]:
        logger.warning(f"Quantified variable '{var_name}' shadows existing symbol")
    context[var_name] = v
```

Variables bound by quantifiers override free variables in local scope.

## Answer Determination

**Implementation:** `z3adapter/backends/abstract.py:52-67`

```python
def determine_answer(self, sat_count: int, unsat_count: int) -> bool | None:
    if sat_count > 0 and unsat_count == 0:
        return True
    elif unsat_count > 0 and sat_count == 0:
        return False
    else:
        return None  # Ambiguous
```

**Ambiguous results** (`None`) occur when:
- `sat_count > 0 and unsat_count > 0` — multiple verifications with conflicting results
- `sat_count == 0 and unsat_count == 0` — no verifications or all unknown

**Handling:** `proof_of_thought.py:183-191` treats `None` as error and retries with feedback:
```python
if verify_result.answer is None:
    error_trace = (
        f"Ambiguous verification result: "
        f"SAT={verify_result.sat_count}, UNSAT={verify_result.unsat_count}"
    )
    continue  # Retry with error feedback
```

**Best practice:** Single verification per program (enforced by prompt template line 416).

## Security Model

**Implementation:** `z3adapter/security/validator.py`

### AST Validation

Before `eval()`, parses to AST and checks for dangerous constructs (lines 21-42):

**Blocked:**
- Dunder attributes: `__import__`, `__class__`, etc. (line 24)
- Imports: `import`, `from ... import` (line 29)
- Function/class definitions (line 32)
- Builtin abuse: `eval`, `exec`, `compile`, `__import__` (line 36-42)

### Restricted Evaluation

```python
# Line 66
eval(code, {"__builtins__": {}}, {**safe_globals, **context})
```

- **No builtins**: `__builtins__: {}` prevents access to `open`, `print`, etc.
- **Whitelisted globals**: Only Z3 operators and user-defined functions
- **Local context**: Constants, variables, quantified vars

**Whitelisted operators** (`expressions.py:33-47`):
```python
Z3_OPERATORS = {
    "And", "Or", "Not", "Implies", "If", "Distinct",
    "Sum", "Product", "ForAll", "Exists", "Function", "Array", "BitVecVal"
}
```

## Sort Dependency Resolution

**Implementation:** `z3adapter/dsl/sorts.py:36-97`

Uses **Kahn's algorithm** for topological sorting.

### Dependency Extraction

ArraySort creates dependencies (lines 59-62):
```python
if sort_type.startswith("ArraySort("):
    domain_range = sort_type[len("ArraySort(") : -1]
    parts = [s.strip() for s in domain_range.split(",")]
    deps.extend(parts)
```

Example:
```json
{"name": "MyArray", "type": "ArraySort(IntSort, Person)"}
```
Depends on: `IntSort` (built-in, skip), `Person` (must be defined first).

### Topological Sort

Kahn's algorithm (lines 66-87):
1. Calculate in-degree (dependency count) for each sort
2. Process sorts with zero dependencies first
3. Reduce in-degree of dependents
4. Detect cycles if not all sorts processed (lines 90-92)

**Circular dependency detection:**
```python
if len(sorted_names) != len(dependencies):
    remaining = set(dependencies.keys()) - set(sorted_names)
    raise ValueError(f"Circular dependency detected in sorts: {remaining}")
```

## Optimizer Independence

**Implementation:** `z3adapter/optimization/optimizer.py:29-39`

```python
def __init__(self, ...):
    self.optimizer = Optimize()  # Separate instance
```

**Critical:** `Optimize()` is **separate from `Solver()`**. Does NOT share constraints.

From docstring (line 38-39):
> The optimizer is separate from the solver and doesn't share constraints.
> This is intentional to allow independent optimization problems.

Optimizer has its own variables and constraints (lines 49-69). Can reference global constants via extended context (line 60-61):
```python
base_context = self.expression_parser.build_context()
opt_context = {**base_context, **optimization_vars}
```

## Execution Pipeline

**Implementation:** `z3adapter/interpreter.py:135-197`

8-step execution sequence:

```python
# Step 1: Create sorts
self.sort_manager.create_sorts(self.config["sorts"])

# Step 2: Create functions
functions = self.sort_manager.create_functions(self.config["functions"])

# Step 3: Create constants
self.sort_manager.create_constants(self.config["constants"])

# Step 4: Create variables
variables = self.sort_manager.create_variables(self.config.get("variables", []))

# Step 5: Initialize expression parser
self.expression_parser = ExpressionParser(functions, constants, variables)
self.expression_parser.mark_symbols_loaded()  # Enable context caching

# Step 6: Add knowledge base
self.expression_parser.add_knowledge_base(self.solver, self.config["knowledge_base"])

# Step 7: Add rules
self.expression_parser.add_rules(self.solver, self.config["rules"], sorts)

# Step 8: Initialize verifier and add verifications
self.verifier = Verifier(self.expression_parser, sorts)
self.verifier.add_verifications(self.config["verifications"])

# Step 9: Perform actions (e.g., "verify_conditions")
self.perform_actions()
```

**Symbol loading:** Line 172 calls `mark_symbols_loaded()` to enable context caching (lines 78-84 in `expressions.py`). After this, `build_context()` returns cached dict instead of rebuilding.

## Retry Mechanism

**Implementation:** `z3adapter/reasoning/proof_of_thought.py:123-191`

Retry loop with error feedback:

```python
for attempt in range(1, self.max_attempts + 1):
    if attempt == 1:
        gen_result = self.generator.generate(question, ...)
    else:
        gen_result = self.generator.generate_with_feedback(
            question, error_trace, previous_response, ...
        )
```

**Failure modes triggering retry:**

1. **Generation failure** (lines 143-149):
   ```python
   if not gen_result.success or gen_result.program is None:
       error_trace = gen_result.error or "Failed to generate program"
       continue
   ```

2. **Execution failure** (lines 176-180):
   ```python
   if not verify_result.success:
       error_trace = verify_result.error or "Z3 verification failed"
       continue
   ```

3. **Ambiguous result** (lines 183-191):
   ```python
   if verify_result.answer is None:
       error_trace = f"Ambiguous verification result: SAT={sat_count}, UNSAT={unsat_count}"
       continue
   ```

**Error feedback:** Multi-turn conversation (`program_generator.py:130-174`):
```python
messages=[
    {"role": "user", "content": prompt},
    {"role": "assistant", "content": previous_response},
    {"role": "user", "content": feedback_message},
]
```

## Solver Semantics

**Implementation:** `z3adapter/solvers/z3_solver.py:20-24`

```python
def check(self, condition: Any = None) -> Any:
    if condition is not None:
        return self.solver.check(condition)  # Temporary hypothesis
    return self.solver.check()               # Check all assertions
```

**Two modes:**

1. **`solver.check()`**: Checks satisfiability of all `solver.add()` assertions
2. **`solver.check(φ)`**: Checks satisfiability of `assertions ∧ φ` **without adding φ**

Verifications use mode 2 (`verifier.py:113`):
```python
result = solver.check(condition)
```

This is **temporary** — `condition` is NOT added to solver permanently.

**Contrast with rules:**
- Rules: `solver.add(φ)` → permanent
- Verifications: `solver.check(φ)` → temporary test

## Built-in Sorts

**Implementation:** `z3adapter/dsl/sorts.py:31-34`

Three built-in sorts pre-initialized:
```python
def _initialize_builtin_sorts(self) -> None:
    built_in_sorts = {"BoolSort": BoolSort(), "IntSort": IntSort(), "RealSort": RealSort()}
    self.sorts.update(built_in_sorts)
```

**Important:** Reference as `"BoolSort"`, `"IntSort"`, `"RealSort"` in JSON (not `"Bool"`, `"Int"`, `"Real"`).

Do NOT declare in `"sorts"` section — already available.

## Prompt Template Constraints

**Implementation:** `z3adapter/reasoning/prompt_template.py`

Key constraints enforced by prompt (extracted from code):

**Line 228:** Rules with `"implies"` MUST have non-empty `"forall"` field
```python
# expressions.py:184-186
if "implies" in rule:
    if not variables:
        raise ValueError("Implication rules require quantified variables")
```

**Line 298:** Empty quantifier lists forbidden
```python
# verifier.py:42-43, 55-56
if not exists_vars:
    raise ValueError(f"Empty 'exists' list in verification")
```

**Line 416:** Single verification per program (avoid ambiguous results)
```python
# Directly impacts determine_answer() — mixed SAT/UNSAT returns None
```

**Line 531:** Output format requirement
- Must wrap JSON in markdown code block: ` ```json ... ``` `
- Regex extraction: `r"```json\s*(\{[\s\S]*?\})\s*```"` (`program_generator.py:224`)
