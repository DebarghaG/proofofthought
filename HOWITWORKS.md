`ProofOfThought` is a groundbreaking initiative designed to solve one of the
most significant challenges in modern artificial intelligence: the tendency of
Large Language Models (LLMs) to "hallucinate" or generate plausible but
logically flawed answers. Its core innovation lies in creating a powerful
hybrid reasoning system that combines the flexible, human-like understanding of
LLMs with the rigorous, verifiable certainty of a formal theorem prover.
Instead of simply trusting an LLM's direct answer, this project tasks the LLM
with a more structured goal: to act as a programmer that translates a user's
question into a symbolic logic program. This program is then executed by the Z3
theorem prover, a trusted engine that guarantees the final `True` or `False`
result is not just a guess, but a conclusion derived from logically consistent
facts and rules. The most inventive aspect is its automated self-correction
loop; if the generated logic program fails, the system feeds the error back to
the LLM, enabling it to learn from its mistakes and refine its reasoning until
it produces a program that is both syntactically correct and logically sound.

Here's how it works:

### 1. High-Level User Query

A user starts by posing a question in natural language to the `ProofOfThought`
class, which is the main high-level API for the system.

```python
from openai import OpenAI
from z3dsl.reasoning import ProofOfThought

client = OpenAI()
pot = ProofOfThought(llm_client=client)
result = pot.query("Would Nancy Pelosi publicly denounce abortion?")
```

### 2. Program Generation via LLM

Instead of answering the question directly, the system uses an LLM (e.g. `GPT-5`) to act as a programmer.

*   **Prompting**: The user's question is embedded into a highly detailed prompt template. This prompt instructs the LLM on how to decompose the question and convert it into a JSON-based Domain-Specific Language (DSL) that represents the problem's logic.
*   **Logical Decomposition**: The LLM breaks down the question. For "Would Nancy Pelosi publicly denounce abortion?", it reasons that:
    1.  Nancy Pelosi is a person and abortion is an issue.
    2.  A known fact is that Nancy Pelosi supports abortion rights.
    3.  A general rule is that people do not publicly denounce things they support.
*   **JSON Program Creation**: The LLM translates this reasoning into a JSON program. This program defines sorts (types like `Person`), constants (`nancy_pelosi`), functions (`supports`), a knowledge base (facts and rules), and a single verification condition to test the original question.

```javascript
// Example generated JSON from the project's documentation
{
  "sorts": [...],
  "functions": [...],
  "constants": {
    "persons": {"sort": "Person", "members": ["nancy_pelosi"]},
    "issues": {"sort": "Issue", "members": ["abortion"]}
  },
  "knowledge_base": [
    {"assertion": "supports(nancy_pelosi, abortion)"},
    {"assertion": "ForAll([p, i], Implies(supports(p, i), Not(publicly_denounce(p, i))))"}
  ],
  "verifications": [
    {"name": "Pelosi Denounce Abortion", "constraint": "publicly_denounce(nancy_pelosi, abortion)"}
  ],
  "actions": ["verify_conditions"]
}
```

### 3. Z3 Theorem Proving

*   **Interpretation**: The generated JSON program is passed to the `Z3JSONInterpreter`. This component reads the file and translates the DSL into commands and assertions for the Z3 theorem prover.
*   **Execution**: The Z3 solver loads the facts from the `"knowledge_base"` and then checks if the `"constraint"` from the `"verifications"` section can be true. The result is one of the following:
    *   **`UNSAT` (Unsatisfiable)**: The constraint contradicts the knowledge base. The system interprets this as `False`.
    *   **`SAT` (Satisfiable)**: The constraint is logically consistent with the knowledge base. The system interprets this as `True`.
    *   **`UNKNOWN`**: The solver timed out.

In the Nancy Pelosi example, Z3 would find that "publicly_denounce(nancy_pelosi, abortion)" is a contradiction to the knowledge base, resulting in `UNSAT` and a final answer of `False`.

### 4. Self-Correction and Error Handling

A key feature of the project is its automatic retry mechanism. If any step fails, the system attempts to correct itself.

*   **JSON or Z3 Errors**: If the LLM generates invalid JSON, or if the Z3 interpreter fails (e.g., due to a logical error in the program), the error message is captured.
*   **Feedback Loop**: The system initiates another call to the LLM. This time, it provides the original question, the faulty program, and the specific error trace. It then asks the LLM to "fix the JSON accordingly."
*   **Retry Attempts**: This feedback loop continues for a configurable number of attempts (`max_attempts`), allowing the LLM to iteratively debug and correct its own generated code.

### 5. Architecture and Evaluation

The project is structured into two main layers, making it both powerful and easy to use:

*   **High-level API (`z3dsl.reasoning`)**: Provides the simple `ProofOfThought` and `EvaluationPipeline` classes for end-users, abstracting away the complex underlying logic.
*   **Low-level DSL (`z3dsl`)**: Consists of the interpreter, verifier, and program generator that handle the core workflow of converting questions to JSON and executing them with Z3.

The system also includes an `EvaluationPipeline` to benchmark performance on
datasets like StrategyQA, automatically calculating metrics such as accuracy,
precision, and recall.
