import io
import json
import logging
import os
import re
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

import numpy as np
from openai import OpenAI
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_score,
    recall_score,
)

from z3adapter.interpreter import Z3JSONInterpreter


def calculate_metrics(y_true: list[Any], y_pred: list[Any]) -> dict[str, Any]:
    y_true = np.array(y_true)
    y_pred = np.array(y_pred)

    # Handle the case where there's only one class
    if len(np.unique(y_true)) == 1 or len(np.unique(y_pred)) == 1:
        accuracy = accuracy_score(y_true, y_pred)
        if np.array_equal(y_true, y_pred):
            if y_true[0] == 1:  # All positive
                tp, fp, tn, fn = len(y_true), 0, 0, 0
            else:  # All negative
                tp, fp, tn, fn = 0, 0, len(y_true), 0
        else:
            if y_true[0] == 1:  # All true positive, some false negative
                tp = np.sum(y_pred)
                fn = len(y_true) - tp
                fp, tn = 0, 0
            else:  # All true negative, some false positive
                y_pred_arr = np.array(y_pred)
                tn = int(np.sum(~y_pred_arr))
                fp = len(y_true) - tn
                tp, fn = 0, 0

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0
        false_positive_rate = fp / (fp + tn) if (fp + tn) > 0 else 0
        false_negative_rate = fn / (fn + tp) if (fn + tp) > 0 else 0
    else:
        cm = confusion_matrix(y_true, y_pred)
        tn, fp, fn, tp = cm.ravel()
        accuracy = accuracy_score(y_true, y_pred)
        precision = precision_score(y_true, y_pred, zero_division=0)
        recall = recall_score(y_true, y_pred, zero_division=0)
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0
        false_positive_rate = fp / (fp + tn) if (fp + tn) > 0 else 0
        false_negative_rate = fn / (fn + tp) if (fn + tp) > 0 else 0

    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

    return {
        "TP": int(tp),
        "FP": int(fp),
        "TN": int(tn),
        "FN": int(fn),
        "Accuracy": accuracy,
        "Precision": precision,
        "Recall": recall,
        "F1 Score": f1,
        "Specificity": specificity,
        "False Positive Rate": false_positive_rate,
        "False Negative Rate": false_negative_rate,
    }


# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# Function to extract JSON from markdown content
def extract_json_from_markdown(markdown_content: str) -> dict[str, Any] | None:
    json_code_block_pattern = r"```json\s*(\{[\s\S]*?\})\s*```"
    match = re.search(json_code_block_pattern, markdown_content)
    if match:
        json_content = match.group(1)
        return json.loads(json_content)  # Parse JSON content
    return None


def run_z3_interpreter(output_json_path: str) -> tuple[bool | None, str]:
    # Capture both stdout and stderr
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
        interpreter = Z3JSONInterpreter(output_json_path)
        interpreter.run()

    # Combine stdout and stderr
    full_output = stdout_capture.getvalue() + stderr_capture.getvalue()

    # Analyze the output
    sat_occurrences = full_output.count(": SAT")
    unsat_occurrences = full_output.count(": UNSAT")

    # Determine the answer
    predicted_answer: bool | None
    if sat_occurrences > 0 and unsat_occurrences == 0:
        predicted_answer = True
    elif unsat_occurrences > 0 and sat_occurrences == 0:
        predicted_answer = False
    else:
        predicted_answer = None

    return predicted_answer, full_output


api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError(
        "OPENAI_API_KEY is not set. " "Please set it in your .env file or environment variables."
    )

client = OpenAI(api_key=api_key)

# Load the StrategyQA dataset
with open("strategyqa_train.json") as f:
    data = json.load(f)

# Set up output directories
output_dir = "strategyqa_outputs"
json_dir = os.path.join(output_dir, "json")
response_dir = os.path.join(output_dir, "responses")

os.makedirs(json_dir, exist_ok=True)
os.makedirs(response_dir, exist_ok=True)

max_questions = 10
correct_answers = 0
wrong_answers = 0
programgenerror = 0

y_true = []
y_pred = []


for idx, question_data in enumerate(data[:max_questions]):
    qid = question_data["qid"]
    question_text = question_data["question"]
    actual_answer = question_data["answer"]  # True or False

    logger.info(f"Processing question {idx+1}/{max_questions}: {qid}")
    logger.info(f"Question: {question_text}")
    logger.info(f"Actual Answer: {actual_answer}")

    output_json_path = os.path.join(json_dir, f"{qid}_extracted.json")
    if os.path.exists(output_json_path):
        logger.info(f"Skipping question {qid}, already processed.")
        continue

    num_attempts = 0
    max_attempts = 3
    success = False

    # Define your prompt template here
    initial_prompt_content = """
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
            - `"BoolSort"`: Boolean type.
            - `"IntSort"`: Integer type.
            - `"RealSort"`: Real number type.
            - `"DeclareSort"`: Custom, uninterpreted sort.
            - `"EnumSort"`: Enumerated sort with specified values.
            - `"BitVecSort(n)"`: Bit vector of size `n`.
            - `"ArraySort(DomainSort, RangeSort)"`: Array mapping from `DomainSort` to `RangeSort`.
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
            {"name": "num_children", "domain": ["Person"], "range": "Int"}
            ```

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

        ### **Good Examples of JSON Programming**

        1. **Example: Correctly Defining Variables for Quantified Expressions**

        **Incorrect - Missing Variable Declaration**:
        ```json
        "knowledge_base": [
            "ForAll([p], Implies(is_law_enforcement(p), can_arrest(p)))"
        ]
        ```

        **Error**: `p` is not defined in the evaluation context, causing a NameError.

        **Corrected Version - Declare in Global Variables Section**:
        ```json
        "variables": [
            {"name": "p", "sort": "Person"}
        ],
        "knowledge_base": [
            "ForAll([p], Implies(is_law_enforcement(p), can_arrest(p)))"
        ]
        ```

        **Explanation**: By declaring `p` in the global `"variables"` section, it becomes available in the evaluation context. The `ForAll` quantifier then binds this variable within its scope.

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

        ### **Revised Guidelines for Writing Good Programs**

        1. **Always Declare Variables in the Global Section**

        - All variables used in quantified expressions (ForAll/Exists) must be declared in the global `"variables"` section.
        - The quantifier automatically binds the variable within its scope, but the variable must exist in the evaluation context.

        2. **Use Correct Field Names**

        - In rules: Use `"forall"` for quantified variables, NOT `"variables"`
        - In verifications: Use `"forall"`, `"exists"`, or no quantifier field for simple constraints
        - In knowledge_base: Do NOT add a `"variables"` field in assertion dictionaries

        3. **Understanding Quantifier Binding**

        - When you write `ForAll([p], ...)`, the variable `p` must be declared in the global `"variables"` section
        - The `ForAll` quantifier then binds `p` within its scope
        - Example:
            ```json
            "variables": [
                {"name": "p", "sort": "Person"}
            ],
            "knowledge_base": [
                "ForAll([p], Implies(condition(p), result(p)))"
            ]
            ```

        4. **Ensure Variables are in Evaluation Context**

        - The interpreter builds an evaluation context from functions, constants, and the global variables section
        - Quantified variables are temporarily added to this context when evaluating their scope
        - Always declare variables globally to make them available for quantification

        ---

        ### **Example of Corrected JSON Program**

        **Question**: Would Nancy Pelosi publicly denounce abortion?

        **Decomposition**:

        - Nancy Pelosi is known to support abortion rights.
        - People do not publicly denounce issues they support.
        - Therefore, Nancy Pelosi would not publicly denounce abortion.

        **JSON Program**:

        ```json
        {
        "sorts": [
            {"name": "Person", "type": "DeclareSort"},
            {"name": "Issue", "type": "DeclareSort"},
            {"name": "Bool", "type": "BoolSort"}
        ],
        "functions": [
            {"name": "supports", "domain": ["Person", "Issue"], "range": "Bool"},
            {"name": "publicly_denounce", "domain": ["Person", "Issue"], "range": "Bool"}
        ],
        "constants": {
            "persons": {
            "sort": "Person",
            "members": ["nancy_pelosi"]
            },
            "issues": {
            "sort": "Issue",
            "members": ["abortion"]
            }
        },
        "variables": [
            {"name": "p", "sort": "Person"},
            {"name": "i", "sort": "Issue"}
        ],
        "knowledge_base": [
            {
            "assertion": "supports(nancy_pelosi, abortion)"
            },
            {
            "assertion": "ForAll([p, i], Implies(supports(p, i), Not(publicly_denounce(p, i))))"
            }
        ],
        "verifications": [
            {
            "name": "Pelosi Denounce Abortion",
            "constraint": "publicly_denounce(nancy_pelosi, abortion)"
            }
        ],
        "actions": ["verify_conditions"]
        }
        ```

        **Explanation**:

        - **Variables Defined**:
        - `p` and `i` are defined in the global `"variables"` section, making them available in the evaluation context.
        - When the `ForAll([p, i], ...)` quantifier is evaluated, these variables are bound within the quantifier's scope.

        - **Knowledge Base Assertions**:
        - The first assertion is a simple fact: Nancy Pelosi supports abortion.
        - The second assertion is a universal rule: For all persons `p` and issues `i`, if `p` supports `i`, then `p` does not publicly denounce `i`.
        - Notice that the ForAll assertion does NOT have a `"variables"` field inside the dictionary - the variables are already declared globally.

        - **Verification**:
        - We check if "publicly_denounce(nancy_pelosi, abortion)" can be true.
        - Expected result: UNSAT (because it contradicts the knowledge base - she supports abortion, so she won't denounce it).

        - **Why This Works**:
        - By declaring `p` and `i` globally, they are available when the interpreter evaluates the ForAll expression.
        - The ForAll quantifier binds these variables, making them quantified variables within its scope.
        - This prevents the "name 'p' is not defined" error during evaluation.

        ---

        ### **Additional Tips**

        - **Define All Quantified Variables Globally**:
        - Any variable used in ForAll/Exists quantifiers must be declared in the global `"variables"` section.
        - This makes them available in the evaluation context so they can be bound by quantifiers.

        - **Simplify Assertions**:
        - Use simple strings for assertions when possible (e.g., `"supports(nancy_pelosi, abortion)"`)
        - Only use dictionary format when you need to specify `"value": false` to negate an assertion.

        - **Test Expressions Separately**:
        - Before including complex expressions in the JSON, test them separately to ensure they are syntactically correct.

        - **Validate JSON Output**:
        - Use tools or online validators to ensure that your JSON is well-formed and free of syntax errors.

        - **Understand the Evaluation Model**:
        - The interpreter evaluates expressions by building a context from functions, constants, and global variables.
        - Quantifiers temporarily add their bound variables to this context during evaluation.
        - This two-level system (global declaration + quantifier binding) prevents name errors.

        ---

        ### **Conclusion**

        By following these updated guidelines and paying close attention to variable declarations and context, you can create JSON-based DSL programs that are free of errors and compatible with the interpreter. Always define all variables used in expressions, use correct syntax, and validate your JSON output. This will help ensure that your programs execute successfully and provide accurate results when processed by the theorem prover.

        ---

        **Task**:

        Think step by step and reason about the given question. Decompose the question into logical reasoning steps, define the necessary sorts, functions, constants, variables, and knowledge base entries, and finally, construct a JSON file representing the problem. Ensure that:

        - All variables used in expressions are properly defined.
        - The JSON structure is valid and free of syntax errors.
        - The logical expressions are syntactically correct and use variables available in the context.

        **Example Task**:

        Given the question:

        *"Would a student of the class of 2017 have amnesia about 9/11?"*

        1. **Decompose the Question**:

        - Determine the typical age of a student graduating in 2017.
        - Calculate the birth year of such a student.
        - Determine if the student was born after the year 2000.
        - People born after 2000 may not remember events from 2001.
        - Therefore, such a student may not remember 9/11.

        2. **Construct the JSON Program**:

        ```json
        {
            "sorts": [
            {"name": "Person", "type": "DeclareSort"},
            {"name": "Int", "type": "IntSort"}
            ],
            "functions": [
            {"name": "graduation_year", "domain": ["Person"], "range": "Int"},
            {"name": "birth_year", "domain": ["Person"], "range": "Int"},
            {"name": "has_amnesia_about_9_11", "domain": ["Person"], "range": "Bool"}
            ],
            "constants": {
            "persons": {
                "sort": "Person",
                "members": ["student"]
            }
            },
            "variables": [
            {"name": "p", "sort": "Person"}
            ],
            "knowledge_base": [
            "graduation_year(student) == 2017",
            "birth_year(student) == graduation_year(student) - 22",
            {
                "assertion": "ForAll([p], Implies(birth_year(p) > 2000, has_amnesia_about_9_11(p)))"
            }
            ],
            "verifications": [
            {
                "name": "Student Has Amnesia About 9/11",
                "constraint": "has_amnesia_about_9_11(student)"
            }
            ],
            "actions": ["verify_conditions"]
        }
        ```

        **Final Note**:

        Make sure to double-check your JSON program for correctness and adherence to the guidelines. The goal is to create a logical representation of the question that can be understood and verified by the theorem prover.

        ---

    SAT is True. UNSAT is False. Answer the following question:

    """

    initial_prompt_content = initial_prompt_content + f"Question: {question_text}"

    prompt_content = initial_prompt_content
    previous_response: str | None = None
    error_trace: str | None = None
    predicted_answer: bool | None = None
    interpreter_output: str = ""

    while num_attempts < max_attempts and not success:
        time.sleep(2)
        num_attempts += 1
        try:
            if num_attempts == 1:
                # First attempt
                messages = [
                    {"role": "user", "content": [{"type": "text", "text": initial_prompt_content}]}
                ]
            else:
                # Subsequent attempts
                messages = [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": previous_response or ""}],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"There was an error processing your response:\n{error_trace}\nPlease fix the JSON accordingly.",
                            }
                            # {"role": "user", "content": [{ "type" : "text", "text" : initial_prompt_content}]},
                        ],
                    },
                ]

            # Make the OpenAI API call
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                temperature=0.1,
                max_tokens=2048,
                top_p=1,
                frequency_penalty=0,
                presence_penalty=0,
                response_format={"type": "text"},
            )

            response_data = response.choices[0].message.content

            # Save the response
            response_path = os.path.join(response_dir, f"{qid}_response_attempt{num_attempts}.json")
            with open(response_path, "w") as f:
                json.dump({"response_content": response_data}, f, indent=4)

            markdown_content = response_data
            previous_response = markdown_content

            extracted_json = extract_json_from_markdown(markdown_content or "")
            if extracted_json:
                with open(output_json_path, "w") as f:
                    json.dump(extracted_json, f, indent=4)
                try:
                    predicted_answer, interpreter_output = run_z3_interpreter(output_json_path)

                    logger.info(f"Interpreter Output:\n{interpreter_output}")

                    if predicted_answer is not None:
                        logger.info(f"Answer Computed : ({predicted_answer}, {actual_answer})")
                        if predicted_answer == actual_answer:
                            correct_answers += 1
                            logger.info(
                                f"Question {qid} answered correctly on attempt {num_attempts}"
                            )
                        else:
                            wrong_answers += 1
                            logger.info(
                                f"Question {qid} answered incorrectly on attempt {num_attempts}"
                            )
                        success = True
                    else:
                        logger.warning(
                            f"Could not determine the answer for question {qid} on attempt {num_attempts}"
                        )
                        error_trace = f"Ambiguous output: SAT and UNSAT occurrences don't clearly indicate an answer.\nFull output:\n{interpreter_output}"
                        success = False

                except Exception as e:
                    error_trace = f"Error running interpreter: {str(e)}\nFull traceback:\n{''.join(traceback.format_exception(type(e), e, e.__traceback__))}"
                    logger.error(
                        f"Error running interpreter for question {qid} on attempt {num_attempts}:\n{error_trace}"
                    )
                    success = False
            else:
                error_trace = "Failed to extract JSON from the response."
                logger.error(f"Failed to extract JSON for question {qid} on attempt {num_attempts}")
                success = False

        except Exception as e:
            error_trace = f"Error processing question: {str(e)}\nFull traceback:\n{''.join(traceback.format_exception(type(e), e, e.__traceback__))}"
            logger.error(
                f"Error processing question {qid} on attempt {num_attempts}:\n{error_trace}"
            )
            success = False

        if not success and num_attempts < max_attempts:
            prompt_content = initial_prompt_content
    if success and predicted_answer is not None:
        print(actual_answer, predicted_answer, type(actual_answer), type(predicted_answer))
        y_true.append(int(actual_answer))
        y_pred.append(int(predicted_answer))

        # # Calculate and log metrics for this question
        # metrics = calculate_metrics(y_true, y_pred)
        # logger.info("Current Metrics:")
        # for metric, value in metrics.items():
        #     logger.info(f"{metric}: {value}")

    if not success:
        logger.error(f"Failed to process question {qid} after {max_attempts} attempts.")
        programgenerror += 1

    logger.info("Current Statistics:")
    logger.info(f"Total correct answers: {correct_answers}")
    logger.info(f"Total wrong answers: {wrong_answers}")
    logger.info(f"Accuracy: {correct_answers / (correct_answers + wrong_answers) * 100:.2f}%")
    logger.info(f"Program has not compiled {programgenerror} times.")

logger.info("Final Results:")
logger.info(f"Total correct answers: {correct_answers}")
logger.info(f"Total wrong answers: {wrong_answers}")
logger.info(f"Final Accuracy: {correct_answers / (correct_answers + wrong_answers) * 100:.2f}%")

# After processing all questions, calculate and log final metrics
final_metrics = calculate_metrics(y_true, y_pred)
print("Y_true", y_true)
print("Y_pred", y_pred)
logger.info("Final Metrics:")
for metric, value in final_metrics.items():
    logger.info(f"{metric}: {value}")

logger.info(f"Total questions processed: {len(y_true)}")
logger.info(f"Program has not compiled {programgenerror} times.")
