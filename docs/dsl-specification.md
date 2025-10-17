# DSL Specification

This page provides technical details of the JSON DSL implementation.

## Rules vs Verifications

Understanding the distinction between rules and verifications is critical to using the DSL correctly.

**Key difference:** Rules modify the solver state, while verifications query it.

### Rules

Rules define axioms that permanently affect the solver's knowledge base.

**Implementation:** `z3adapter/dsl/expressions.py:159-204`

**Operation:** `solver.add(assertion)`

Rules are permanently asserted into the solver's knowledge base during step 6 of the interpretation pipeline.

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

**Effect:** This defines an axiom that every subsequent verification will inherit.

### Verifications

Verifications test conditions without modifying the knowledge base.

**Implementation:** `z3adapter/verification/verifier.py:84-127`

**Operation:** `solver.check(condition)`

Verifications test conditions against the existing knowledge base without modifying it.

```python
# Line 113
result = solver.check(condition)  # Temporary hypothesis check

if result == sat:
    self.sat_count += 1
elif result == unsat:
    self.unsat_count += 1
```

**Semantics:** The check determines if `KB ∧ condition` is satisfiable.

- **SAT**: The condition is consistent with the knowledge base
- **UNSAT**: The condition contradicts the knowledge base

**Structure:**
```json
{
  "name": "test_pelosi",
  "constraint": "publicly_denounce(nancy, abortion)"
}
```

**Effect:** Returns SAT/UNSAT result but does NOT add the condition to the knowledge base.

### Example

Here's a complete example showing the interaction between rules and verifications:

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

The DSL supports both free and quantified variables with careful scoping rules.

**Implementation:** `z3adapter/dsl/expressions.py:69-107`

### Free Variables

Free variables are declared in the global `"variables"` section and remain available throughout the program.

```json
"variables": [{"name": "x", "sort": "Int"}]
```

These are added to the evaluation context at line 91:

```python
context.update(self.variables)
```

### Quantified Variables

Quantified variables are bound by `ForAll` or `Exists` operators and temporarily shadow free variables within their scope.

```json
"knowledge_base": ["ForAll([x], x > 0)"]
```

In this example, `x` must already exist in the context (from `"variables"`) to be bound by the `ForAll` operator.

### Shadowing

The implementation includes shadowing checks at lines 100-106:
```python
for v in quantified_vars:
    var_name = v.decl().name()
    if var_name in context and var_name not in [...]:
        logger.warning(f"Quantified variable '{var_name}' shadows existing symbol")
    context[var_name] = v
```

When shadowing occurs, variables bound by quantifiers take precedence over free variables within their local scope.

## Answer Determination

The system determines the final answer based on verification counts.

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

**Ambiguous results** (returning `None`) occur in two cases:

- `sat_count > 0 and unsat_count > 0` — multiple verifications produced conflicting results
- `sat_count == 0 and unsat_count == 0` — no verifications ran or all returned unknown

**Handling:** The system treats `None` as an error and retries with feedback (see `proof_of_thought.py:183-191`):
```python
if verify_result.answer is None:
    error_trace = (
        f"Ambiguous verification result: "
        f"SAT={verify_result.sat_count}, UNSAT={verify_result.unsat_count}"
    )
    continue  # Retry with error feedback
```

**Best practice:** Use a single verification per program to avoid ambiguous results. This is enforced by the prompt template at line 416.

## Security Model

The DSL includes multiple security layers to prevent code injection attacks.

**Implementation:** `z3adapter/security/validator.py`

### AST Validation

Before executing `eval()`, the system parses expressions to an AST and checks for dangerous constructs (lines 21-42).

**Blocked constructs:**
- Dunder attributes: `__import__`, `__class__`, etc. (line 24)
- Imports: `import`, `from ... import` (line 29)
- Function/class definitions (line 32)
- Builtin abuse: `eval`, `exec`, `compile`, `__import__` (line 36-42)

### Restricted Evaluation

The evaluation environment is carefully sandboxed:

```python
# Line 66
eval(code, {"__builtins__": {}}, {**safe_globals, **context})
```

Three layers of protection:

- **No builtins**: Setting `__builtins__: {}` prevents access to `open`, `print`, and other dangerous functions
- **Whitelisted globals**: Only Z3 operators and user-defined functions are available
- **Local context**: Limited to constants, variables, and quantified variables

**Whitelisted operators** (from `expressions.py:33-47`):
```python
Z3_OPERATORS = {
    "And", "Or", "Not", "Implies", "If", "Distinct",
    "Sum", "Product", "ForAll", "Exists", "Function", "Array", "BitVecVal"
}
```

## Sort Dependency Resolution

Complex types may depend on other types, requiring careful ordering during creation.

**Implementation:** `z3adapter/dsl/sorts.py:36-97`

The system uses **Kahn's algorithm** for topological sorting of type definitions.

### Dependency Extraction

ArraySort declarations create dependencies that must be resolved (lines 59-62):
```python
if sort_type.startswith("ArraySort("):
    domain_range = sort_type[len("ArraySort(") : -1]
    parts = [s.strip() for s in domain_range.split(",")]
    deps.extend(parts)
```

For example:

```json
{"name": "MyArray", "type": "ArraySort(IntSort, Person)"}
```

This depends on: `IntSort` (built-in, can skip) and `Person` (must be defined first).

### Topological Sort

Kahn's algorithm processes types in dependency order (lines 66-87):

1. Calculate the in-degree (dependency count) for each sort
2. Process sorts with zero dependencies first
3. Reduce the in-degree of dependent sorts as their dependencies are satisfied
4. Detect cycles if not all sorts can be processed (lines 90-92)

**Circular dependency detection:**
```python
if len(sorted_names) != len(dependencies):
    remaining = set(dependencies.keys()) - set(sorted_names)
    raise ValueError(f"Circular dependency detected in sorts: {remaining}")
```

## Optimizer Independence

The optimizer operates independently from the main solver.

**Implementation:** `z3adapter/optimization/optimizer.py:29-39`

```python
def __init__(self, ...):
    self.optimizer = Optimize()  # Separate instance
```

**Critical detail:** The `Optimize()` instance is completely separate from the main `Solver()` and does NOT share constraints.

As stated in the docstring (line 38-39):
> The optimizer is separate from the solver and doesn't share constraints.
> This is intentional to allow independent optimization problems.

The optimizer maintains its own variables and constraints (lines 49-69). However, it can reference global constants through an extended context (line 60-61):
```python
base_context = self.expression_parser.build_context()
opt_context = {**base_context, **optimization_vars}
```

## Execution Pipeline

The interpreter follows a carefully ordered execution sequence.

**Implementation:** `z3adapter/interpreter.py:135-197`

**8-step execution sequence:**

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

**Symbol loading optimization:** At line 172, calling `mark_symbols_loaded()` enables context caching (see lines 78-84 in `expressions.py`). After this point, `build_context()` returns a cached dictionary instead of rebuilding it on each call.

## Retry Mechanism

The system can automatically retry failed program generation with error feedback.

**Implementation:** `z3adapter/reasoning/proof_of_thought.py:123-191`

**Retry loop with error feedback:**

```python
for attempt in range(1, self.max_attempts + 1):
    if attempt == 1:
        gen_result = self.generator.generate(question, ...)
    else:
        gen_result = self.generator.generate_with_feedback(
            question, error_trace, previous_response, ...
        )
```

**Failure modes that trigger retry:**

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

**Error feedback mechanism:** Uses multi-turn conversation (see `program_generator.py:130-174`):
```python
messages=[
    {"role": "user", "content": prompt},
    {"role": "assistant", "content": previous_response},
    {"role": "user", "content": feedback_message},
]
```

## Solver Semantics

The solver's `check` method has two distinct modes of operation.

**Implementation:** `z3adapter/solvers/z3_solver.py:20-24`

```python
def check(self, condition: Any = None) -> Any:
    if condition is not None:
        return self.solver.check(condition)  # Temporary hypothesis
    return self.solver.check()               # Check all assertions
```

**Two modes of operation:**

1. **`solver.check()`**: Checks the satisfiability of all assertions added via `solver.add()`
2. **`solver.check(φ)`**: Checks the satisfiability of `assertions ∧ φ` **without permanently adding φ**

Verifications use mode 2 (see `verifier.py:113`):
```python
result = solver.check(condition)
```

This is a **temporary** check — the `condition` is NOT permanently added to the solver.

**Contrast with rules:**

- **Rules**: `solver.add(φ)` → permanently modifies solver state
- **Verifications**: `solver.check(φ)` → temporary test without modification

## Built-in Sorts

The DSL includes three pre-initialized built-in sorts.

**Implementation:** `z3adapter/dsl/sorts.py:31-34`
```python
def _initialize_builtin_sorts(self) -> None:
    built_in_sorts = {"BoolSort": BoolSort(), "IntSort": IntSort(), "RealSort": RealSort()}
    self.sorts.update(built_in_sorts)
```

**Important:** Always reference these as `"BoolSort"`, `"IntSort"`, and `"RealSort"` in JSON (not `"Bool"`, `"Int"`, or `"Real"`).

These sorts are already available and should NOT be declared in the `"sorts"` section.

## Prompt Template Constraints

The prompt template enforces several important constraints on DSL programs.

**Implementation:** `z3adapter/reasoning/prompt_template.py`

**Key constraints** (extracted from code):

### Line 228: Implication Rules

Rules with `"implies"` MUST have non-empty `"forall"` field:

```python
# expressions.py:184-186
if "implies" in rule:
    if not variables:
        raise ValueError("Implication rules require quantified variables")
```

### Line 298: Quantifier Lists

Empty quantifier lists are forbidden:

```python
# verifier.py:42-43, 55-56
if not exists_vars:
    raise ValueError(f"Empty 'exists' list in verification")
```

### Line 416: Single Verification

Use a single verification per program to avoid ambiguous results:

```python
# Directly impacts determine_answer() — mixed SAT/UNSAT returns None
```

### Line 531: Output Format

LLM output requirements:

- Must wrap JSON in a markdown code block: ` ```json ... ``` `
- Extracted via regex: `r"```json\s*(\{[\s\S]*?\})\s*```"` (see `program_generator.py:224`)
