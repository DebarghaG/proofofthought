"""Prompt template for Z3 DSL program generation."""

DSL_INSTRUCTIONS = """
** Instructions for Generating JSON-Based DSL Programs for Theorem Proving**

**Introduction**

This document provides comprehensive guidelines for generating JSON-based Domain-Specific Language (DSL) programs designed to solve complex reasoning tasks using a theorem prover. The goal is to translate reasoning problems into structured JSON programs that can be parsed by a custom interpreter and reliably solved. This guide includes detailed explanations of each section, examples, and emphasizes common pitfalls to avoid to ensure that the generated programs are error-free and adhere strictly to the expected format.

---

### **Important Guidelines to Avoid Common Errors**

1. **Variable Definitions**

- **Understand the difference between FREE variables and QUANTIFIED variables:**
    - **Free Variables**: Declared in the global `"variables"` section. These are variables used in non-quantified contexts (e.g., directly in assertions without ForAll/Exists).
    - **Quantified Variables**: Variables bound by `ForAll` or `Exists` quantifiers. These are automatically bound by the quantifier itself and should NOT be declared in a separate `"variables"` field.

- **Example of Correct Variable Declaration:**
    ```json
    "variables": [
    {"name": "p", "sort": "Person"},
    {"name": "i", "sort": "Issue"}
    ]
    ```
    This declares `p` and `i` as free variables available throughout the program.

    For quantified variables in ForAll/Exists:
    ```json
    "knowledge_base": [
    "ForAll([p, i], Implies(supports(p, i), Not(publicly_denounce(p, i))))"
    ]
    ```
    Here, `p` and `i` are automatically bound by the `ForAll` quantifier. If `p` and `i` are declared in the global `"variables"` section, they can be referenced as free variables within the quantified expression.

2. **Context in Evaluations**

- The interpreter evaluates expressions in a context that includes:
    - **Functions**: Defined in the `"functions"` section.
    - **Constants**: Defined in the `"constants"` section.
    - **Free Variables**: Defined in the global `"variables"` section.
    - **Quantified Variables**: Temporarily added to context when evaluating quantified expressions (ForAll/Exists).

- **Understanding Variable Scope**:
    - **Free variables** in the global `"variables"` section are available throughout the entire program.
    - **Quantified variables** (e.g., in `ForAll([x], ...)`) are automatically bound by the quantifier and available only within that quantified expression.
    - You can reference free variables inside quantified expressions, creating nested scopes.

3. **Valid JSON Output**

- **Ensure that the JSON output is valid and can be parsed without errors.**
    - Use proper syntax, including commas, quotation marks, and matching brackets.
    - Avoid trailing commas or missing commas between elements.

- **Common JSON Errors to Avoid**:
    - Missing commas between array elements or object properties.
    - Unmatched brackets or braces.
    - Incorrect use of quotation marks.

- **Recommendation**:
    - Use a JSON validator or formatter to check the generated JSON before finalizing it.

4. **Correct Syntax in Logical Expressions**

- **Use Proper Python Syntax for Expressions**:
    - When writing expressions that will be evaluated, ensure they are valid Python expressions.
    - For example, in the assertion `ForAll([p], ...)`, `p` must be defined in the context or within the quantifier.

- **Avoid Using Unrecognized Variables**:
    - Do not use variables in expressions that have not been defined.
    - If a variable is introduced in a quantifier, ensure it is properly included.

- **Example of Correct Usage**:
    ```json
    "variables": [
    {"name": "p", "sort": "Person"}
    ],
    "knowledge_base": [
    "ForAll([p], Implies(is_law_enforcement(p), can_arrest(p)))"
    ]
    ```
    Where `p` is declared as a free variable in the global `"variables"` section, then bound by the `ForAll` quantifier in the assertion.

---

### **Detailed Explanation of Each Section**

1. **Sorts**

- **Purpose**: Define the types or domains (e.g., integers, booleans, custom types like "Person").
- **Structure**:
    ```json
    {
    "name": "SortName",
    "type": "SortType"
    }
    ```
- **Sort Types**:
    - `"BoolSort"`: Boolean type. **Note: When referencing this sort in functions/variables, use "BoolSort" not "Bool".**
    - `"IntSort"`: Integer type. **Note: When referencing this sort in functions/variables, use "IntSort" not "Int".**
    - `"RealSort"`: Real number type. **Note: When referencing this sort in functions/variables, use "RealSort" not "Real".**
    - `"DeclareSort"`: Custom, uninterpreted sort.
    - `"EnumSort"`: Enumerated sort with specified values.
    - `"BitVecSort(n)"`: Bit vector of size `n`.
    - `"ArraySort(DomainSort, RangeSort)"`: Array mapping from `DomainSort` to `RangeSort`.
- **Built-in Sorts**: The sorts `BoolSort`, `IntSort`, and `RealSort` are pre-defined and do NOT need to be declared in the `"sorts"` section.
- **Example**:
    ```json
    {"name": "Person", "type": "DeclareSort"}
    ```

2. **Functions**

- **Purpose**: Define operations or relations between sorts.
- **Structure**:
    ```json
    {
    "name": "FunctionName",
    "domain": ["Sort1", "Sort2"],
    "range": "ReturnSort"
    }
    ```
- **Example**:
    ```json
    {"name": "num_children", "domain": ["Person"], "range": "IntSort"},
    {"name": "is_valid", "domain": ["Person"], "range": "BoolSort"}
    ```
- **Important**: Use the full sort names: "BoolSort", "IntSort", "RealSort", not "Bool", "Int", "Real".

3. **Constants**

- **Purpose**: Represent fixed elements within sorts.
- **Structure**:
    ```json
    {
    "Category": {
        "sort": "SortName",
        "members": ["Const1", "Const2"]
    }
    }
    ```
- **Example**:
    ```json
    {
    "persons": {
        "sort": "Person",
        "members": ["genghis_khan", "julius_caesar"]
    }
    }
    ```

4. **Variables**

- **Purpose**: Define FREE variables that can be used throughout the program. These are symbols that can be referenced in assertions, rules, and verifications. They are particularly useful when you want to use the same variable symbol in multiple quantified expressions.
- **Structure**:
    ```json
    {
    "name": "VariableName",
    "sort": "SortName"
    }
    ```
- **Example**:
    ```json
    {"name": "x", "sort": "Int"}
    ```
- **Note**: Variables declared here can be used as free variables OR can be bound by quantifiers (ForAll/Exists) in assertions. When bound by a quantifier, they become quantified variables within that scope.

5. **Knowledge Base**

- **Purpose**: A set of axioms or facts that are assumed to be true.
- **Structure**: An array of assertions, each representing a logical expression.
- **Assertions** can be simple strings or dictionaries specifying the assertion and its truth value.
- **Example**:
    ```json
    "variables": [
    {"name": "p", "sort": "Person"}
    ],
    "knowledge_base": [
    "ForAll([p], Implies(is_law_enforcement(p), can_arrest(p)))",
    "num_children(genghis_khan) == 16",
    {
        "assertion": "can_fly(superman)",
        "value": true
    }
    ]
    ```
- **Note**: When using quantifiers like ForAll/Exists, the variables must be declared in the global `"variables"` section to be available in the evaluation context.

6. **Rules**

- **Purpose**: Define general logical implications or constraints.
- **Structure**:
    ```json
    {
    "name": "RuleName",
    "forall": [
        {"name": "Var1", "sort": "Sort1"},
        {"name": "Var2", "sort": "Sort2"}
    ],
    "implies": {
        "antecedent": "LogicalExpression",
        "consequent": "LogicalExpression"
    }
    }
    ```
    Or for simple constraints:
    ```json
    {
    "name": "RuleName",
    "constraint": "LogicalExpression"
    }
    ```
- **Example**:
    ```json
    {
    "name": "Greater Than Rule",
    "forall": [
        {"name": "a", "sort": "Int"},
        {"name": "b", "sort": "Int"}
    ],
    "implies": {
        "antecedent": "a > b",
        "consequent": "Not(b > a)"
    }
    }
    ```
- **Important**: Rules with `"implies"` MUST have a `"forall"` field with at least one variable. The `"forall"` field cannot be empty. For rules without quantification, use `"constraint"` instead.

7. **Verifications**

- **Purpose**: Specify properties or conditions that need to be verified by the theorem prover.
- **Three Types of Verifications**:

    **Type 1: Simple Constraint (no quantifiers)**
    ```json
    {
    "name": "VerificationName",
    "constraint": "LogicalExpression"
    }
    ```
    Example:
    ```json
    {
    "name": "Compare Descendants",
    "constraint": "num_descendants(genghis_khan) > num_descendants(julius_caesar)"
    }
    ```

    **Type 2: Existential Verification (checking if there exists a value)**
    ```json
    {
    "name": "VerificationName",
    "exists": [
        {"name": "Var", "sort": "Sort"}
    ],
    "constraint": "LogicalExpression"
    }
    ```
    Example:
    ```json
    {
    "name": "Find Positive Number",
    "exists": [
        {"name": "x", "sort": "Int"}
    ],
    "constraint": "And(x > 0, x < 10)"
    }
    ```

    **Type 3: Universal Verification (checking if property holds for all values)**
    ```json
    {
    "name": "VerificationName",
    "forall": [
        {"name": "Var", "sort": "Sort"}
    ],
    "implies": {
        "antecedent": "LogicalExpression",
        "consequent": "LogicalExpression"
    }
    }
    ```
    Example:
    ```json
    {
    "name": "All Positive Numbers Greater Than Zero",
    "forall": [
        {"name": "x", "sort": "Int"}
    ],
    "implies": {
        "antecedent": "x > 0",
        "consequent": "x >= 1"
    }
    }
    ```

- **Important**: The `"exists"` and `"forall"` fields cannot be empty. They must contain at least one variable definition.

8. **Optimization** (Optional)

- **Purpose**: Define optimization problems with variables, constraints, and objectives.
- **Structure**:
    ```json
    {
    "variables": [
        {"name": "Var", "sort": "Sort"}
    ],
    "constraints": ["LogicalExpression"],
    "objectives": [
        {
        "type": "minimize" or "maximize",
        "expression": "ArithmeticExpression"
        }
    ]
    }
    ```
- **Example**:
    ```json
    {
    "variables": [
        {"name": "x", "sort": "Int"}
    ],
    "constraints": [
        "x >= 0",
        "x <= 10"
    ],
    "objectives": [
        {
        "type": "maximize",
        "expression": "x"
        }
    ]
    }
    ```

9. **Actions**

- **Purpose**: Specify which actions the interpreter should perform.
- **Possible Actions**:
    - `"verify_conditions"`: Runs verifications.
    - `"optimize"`: Solves optimization problems.
- **Structure**: An array of action strings.
- **Example**:
    ```json
    ["verify_conditions"]
    ```

---

### **Understanding Verification Semantics**

**Important: What Does SAT/UNSAT Mean?**

When you run verifications, the interpreter checks the satisfiability of your constraint given the knowledge base:

- **SAT (Satisfiable)**: The constraint CAN be true given the knowledge base. The solver found a model where both the knowledge base AND the constraint are satisfied simultaneously.
  - This means the constraint is CONSISTENT with the knowledge base.
  - A model (example values) will be shown.

- **UNSAT (Unsatisfiable)**: The constraint CONTRADICTS the knowledge base. There is no possible model where both the knowledge base and the constraint can be true together.
  - This means the constraint is INCONSISTENT with the knowledge base.

- **UNKNOWN**: The solver timed out or couldn't determine satisfiability.

**Checking Different Types of Properties:**

1. **To check if a property CAN be true** (satisfiability):
   - Add it directly to verifications
   - SAT = yes, it's possible
   - UNSAT = no, it contradicts the knowledge base

2. **To check if a property MUST be true** (entailment, KB ⊨ φ):
   - Verify that the NEGATION of the property is UNSAT
   - If KB ∧ ¬φ is UNSAT, then KB ⊨ φ (the knowledge base entails the property)
   - Example: To prove "publicly_denounce(nancy_pelosi, abortion)" is false given KB, check if "publicly_denounce(nancy_pelosi, abortion)" is UNSAT

**Example**:
```json
"verifications": [
    {
        "name": "Can Pelosi Denounce Abortion",
        "constraint": "publicly_denounce(nancy_pelosi, abortion)"
    }
]
```
- If this returns SAT: Pelosi denouncing abortion is consistent with the knowledge base
- If this returns UNSAT: Pelosi denouncing abortion contradicts the knowledge base (meaning she definitely won't)

---

### **Available Operators and Functions**

- **Logical Operators**:
- `And(expr1, expr2, ...)`
- `Or(expr1, expr2, ...)`
- `Not(expr)`
- `Implies(antecedent, consequent)`
- `If(condition, true_expr, false_expr)`
- `Distinct(expr1, expr2, ...)`

- **Quantifiers**:
- `ForAll([vars], expr)`
- `Exists([vars], expr)`

- **Arithmetic Operators**:
- `+`, `-`, `*`, `/`
- Comparison: `==`, `!=`, `<`, `<=`, `>`, `>=`

- **Custom Functions**: Defined in the `"functions"` section.

---

### **Verification Strategy Guide**

**CRITICAL: Create ONE Verification Per Question**

When answering a question, create **exactly ONE verification condition** that directly tests what the question asks. Do NOT create multiple verifications testing both the positive and negative cases - this leads to ambiguous results.

**Question Type Strategies:**

1. **"Can/Could X do Y?" or "Is it possible that X...?"** (Possibility questions)
   - Create a single verification checking if the property CAN be satisfied
   - Use `exists` if checking for at least one example
   - ✓ Example: "Can fish breathe underwater?"
   ```json
   "verifications": [
       {
           "name": "Can fish breathe underwater",
           "exists": [{"name": "f", "sort": "Animal"}],
           "constraint": "And(is_fish(f), can_breathe_underwater(f))"
       }
   ]
   ```
   - SAT = Yes, it's possible | UNSAT = No, it contradicts the facts

2. **"Would/Does X do Y?" or "Is X true?"** (Factual questions)
   - Create a single verification checking if the statement is consistent with facts
   - ✓ Example: "Would Nancy Pelosi publicly denounce abortion?"
   ```json
   "verifications": [
       {
           "name": "Would Pelosi denounce abortion",
           "constraint": "publicly_denounce(nancy_pelosi, abortion)"
       }
   ]
   ```
   - SAT = Yes, it's consistent with the facts | UNSAT = No, it contradicts the facts

3. **"Is X always/never true?"** (Universal questions)
   - Use `forall` to check all cases
   - ✓ Example: "Do all birds fly?"
   ```json
   "verifications": [
       {
           "name": "All birds can fly",
           "forall": [{"name": "b", "sort": "Animal"}],
           "implies": {
               "antecedent": "is_bird(b)",
               "consequent": "can_fly(b)"
           }
       }
   ]
   ```

**CRITICAL RULES:**
- ✓ **DO**: Create one clear verification that directly answers the question
- ✗ **DON'T**: Create multiple verifications testing both positive AND negative (e.g., "exists a fish that breathes underwater" AND "exists a fish that doesn't breathe underwater")
- ✗ **DON'T**: Test the inverse/negation unless the question specifically asks about it
- ✗ **DON'T**: Create redundant verifications that check the same thing different ways

**Example of WRONG approach** (causes ambiguous results):
```json
// DON'T DO THIS - Multiple verifications testing opposite things
"verifications": [
    {"name": "Fish can breathe", "constraint": "can_breathe_underwater(fish)"},
    {"name": "Fish cannot breathe", "constraint": "Not(can_breathe_underwater(fish))"}
]
// This gives SAT=1, UNSAT=1 = AMBIGUOUS!
```

---

### **Common Pitfalls to Avoid**

- **Undefined Variables**: Always define variables in the global `"variables"` section if they will be used in quantified expressions (ForAll/Exists). The quantifier binds the variable, but it must exist in the evaluation context first.

- **Using 'variables' field in assertions**: Do NOT add a `"variables"` field inside knowledge_base assertions. Variables should be declared in the global `"variables"` section only.

- **Using 'variables' instead of 'forall' in rules**: Rules must use `"forall"` for quantified variables, not `"variables"`.

- **Empty quantifier lists**: If you specify `"forall"` or `"exists"` in rules or verifications, they must contain at least one variable. Empty lists will cause errors.

- **Syntax Errors in Expressions**: Use correct syntax in logical expressions. Avoid typos and ensure that all parentheses and commas are correctly placed.

- **Invalid JSON**: Double-check the JSON structure for validity. Use a JSON linter or validator if necessary.

- **Misunderstanding SAT/UNSAT**: Remember that SAT means "possible/consistent" and UNSAT means "contradicts". To prove something MUST be true, check if its negation is UNSAT.

---

### **Conclusion**

By following these updated guidelines and paying close attention to variable declarations and context, you can create JSON-based DSL programs that are free of errors and compatible with the interpreter. Always define all variables used in expressions, use correct syntax, and validate your JSON output. This will help ensure that your programs execute successfully and provide accurate results when processed by the theorem prover.

---

**Task**:

Think step by step and reason about the given question. Decompose the question into logical reasoning steps, define the necessary sorts, functions, constants, variables, and knowledge base entries, and finally, construct a JSON file representing the problem. Ensure that:

- All variables used in expressions are properly defined.
- The JSON structure is valid and free of syntax errors.
- The logical expressions are syntactically correct and use variables available in the context.
- **Create EXACTLY ONE verification** that directly answers the question - do NOT create multiple verifications testing opposite cases.

**IMPORTANT: Output Format**

Your response MUST be wrapped in a markdown code block with the ```json``` tag like this:

```json
{
  "sorts": [...],
  "functions": [...],
  ...
}
```

Do NOT output raw JSON without the markdown code block. The parser expects the JSON to be enclosed in ```json ... ``` markers.

SAT is True. UNSAT is False. Answer the following question:

"""


def build_prompt(question: str) -> str:
    """Build the complete prompt for JSON DSL generation.

    Args:
        question: The reasoning question to answer

    Returns:
        Complete prompt string
    """
    return DSL_INSTRUCTIONS + f"\nQuestion: {question}"
