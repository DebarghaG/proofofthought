## How `ProofOfThought` Works

`ProofOfThought` solves one of the most significant challenges in modern
artificial intelligence: the tendency of Large Language Models (LLMs) to
"hallucinate" or generate plausible but *logically flawed* answers. Its core
innovation lies in creating a powerful hybrid reasoning system that combines
the flexible, human-like understanding of LLMs with the rigorous, verifiable
certainty of a formal theorem prover.  Instead of simply trusting an LLM's
direct answer, this project tasks the LLM with a more structured goal: to act
as a programmer that translates a user's question into a symbolic logic
program. This program is then executed by the Z3 theorem prover, a trusted
engine that guarantees the final `True` or `False` result is not just a guess,
but a conclusion derived from logically consistent facts and rules. The most
inventive aspect is its automated self-correction loop; if the generated logic
program fails, the system feeds the error back to the LLM, enabling it to learn
from its mistakes and refine its reasoning until it produces a program that is
both syntactically correct and logically sound.

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

## Limitations and Security Considerations

While the ProofOfThought architecture is innovative in its use of Z3 as a
logical backstop, the LLM's role as the "programmer" remains a potential point
of failure, especially concerning bias and fallacies.

For a large system where manual inspection is impossible, ensuring logical
integrity requires a multi-layered, automated "defense-in-depth" strategy.
Here’s how you could approach this:

### 1. Advanced Prompt Engineering and Constraints

The first line of defense is to constrain the LLM's behavior before it even
generates the program.

*   **Principle of Charity and Neutrality:** The prompt can be explicitly engineered to instruct the LLM to act as a neutral logician. You can include instructions like: "Adhere to the principle of charity: represent all arguments and premises in their strongest, most plausible form, not as caricatures. Avoid using emotionally loaded terms in function or constant names. Decompose facts into neutral, verifiable statements."
*   **Mandatory Assumption Listing:** For questions involving subjective or ambiguous topics, you can require the LLM to create a specific section in its reasoning (or even within the JSON) called `"Assumptions"`. This makes implicit biases explicit. For example, in a political question, an assumption might be `"The primary goal of a political party is to win elections."` This assumption can then be flagged for review.
*   **Fallacy Checklist Instruction:** The prompt can conclude with a command: "Before finalizing the program, review your logical decomposition for common fallacies, including *ad hominem*, *straw man*, *false dichotomy*, and *overgeneralization*. If any are present, reformulate the logic to be more precise."

### 2. Automated Program Auditing (The Most Critical Step)

This is where you build automated systems to inspect the generated JSON program *before* it gets to the Z3 solver. This is the scalable replacement for manual reading.

*   **The "Auditor LLM" Pattern:** A powerful technique is to use a second, independent LLM as a dedicated auditor.
    *   **How it works:** The first LLM (the "Programmer") generates the JSON. This JSON is then passed to a second LLM (the "Auditor") with a completely different prompt: *"You are a specialist in detecting logical fallacies and cognitive biases. Analyze the following JSON program. Does the 'knowledge_base' contain biased assumptions, stereotypes, or fallacious reasoning? Is the 'verification' constraint a neutral and accurate representation of the original question? Provide a 'risk score' from 1-10 and explain your reasoning."*
    *   **Why it's effective:** This creates an adversarial setup. The Auditor LLM isn't tasked with solving the problem, only with critiquing the logic. It's more likely to catch flaws. If the risk score is high, the program can be rejected and sent back to the Programmer LLM with the Auditor's feedback.

*   **Semantic Rule-Based Checkers:** You can programmatically scan the generated JSON for common fallacy patterns:
    *   **Overgeneralization (`ForAll` misuse):** Automatically flag any `ForAll` quantifier that applies to a broad, diverse class of humans with a subjective predicate. For example, a rule like `"ForAll([p], Implies(is_politician(p), is_dishonest(p)))"` is a gross overgeneralization and can be caught by a simple programmatic check.
    *   **Ad Hominem Detection:** Scan for functions that attack a person's character rather than their arguments. Functions named `is_untrustworthy(person)` or `has_bad_motives(person)` are red flags that can be automatically detected.
    *   **Source Citation Requirement:** Modify the system to require the LLM to add metadata to its `knowledge_base` facts, indicating their source (e.g., `"assertion": "supports(nancy_pelosi, abortion)", "source": "public voting record"`). The automated auditor can then flag any "facts" that are asserted without a source.

### 3. Leveraging the Z3 Solver Itself for Sanity Checks

While Z3 can't detect bias in premises, it is the ultimate tool for detecting logical contradictions that often arise from flawed or biased reasoning.

*   **Detecting Inconsistent Biases:** Sometimes, an LLM might introduce multiple, contradictory biases into the knowledge base. For instance, it might assert `"All regulations harm the economy"` and also `"Environmental regulations are necessary for long-term growth."` Before even checking the main verification, the system can ask Z3 to simply check if the `knowledge_base` is consistent on its own. If Z3 returns `UNSAT`, it means the LLM's foundational axioms are contradictory, and the program can be rejected without further analysis.

### 4. System-Level Architectural Patterns

For extremely high-stakes applications, more complex system designs can be used.

*   **Multi-Agent Debate:** Instead of one LLM, have three independent LLMs generate a logic program for the same question. Then, a "Reconciler" agent (which could be another LLM or a programmatic rule-set) compares the three programs. If they all agree on the logical structure, confidence is high. If they differ, it indicates ambiguity or potential bias, and the system can flag the question for human review or request clarification.
*   **Human-in-the-Loop (HITL) for Edge Cases:** No automated system will be perfect. The goal is to automate the 99% of straightforward cases and reliably flag the 1% that are problematic. The automated auditors can route high-risk, ambiguous, or socially sensitive questions to a human expert dashboard for review. This is the scalable version of "reading everything"—you only read what the machine isn't sure about.

By implementing these layers, you move from a position of "trusting the LLM" to a system where the LLM's output is continuously verified, audited, and stress-tested, making it far more robust and less susceptible to the subtle biases and fallacies that are inherent in its training data.
