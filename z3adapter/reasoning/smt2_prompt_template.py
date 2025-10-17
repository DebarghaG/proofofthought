"""Prompt template for SMT-LIB 2.0 program generation."""

SMT2_INSTRUCTIONS = """
**Instructions for Generating SMT-LIB 2.0 Programs for Theorem Proving**

**Introduction**

This document provides comprehensive guidelines for generating SMT-LIB 2.0 programs to solve complex reasoning tasks using the Z3 theorem prover. You will translate reasoning problems into structured SMT2 programs that can be executed directly by Z3.

---

### **Important Guidelines**

1. **SMT-LIB 2.0 Syntax**
   - All commands must be S-expressions: `(command args...)`
   - Comments start with `;`
   - Whitespace is flexible but use consistent indentation

2. **Program Structure**
   ```smt2
   ; 1. Declare sorts
   (declare-sort SortName 0)

   ; 2. Declare functions
   (declare-fun function-name (ArgSort1 ArgSort2) ReturnSort)

   ; 3. Declare constants
   (declare-const constant-name Sort)

   ; 4. Assert knowledge base (facts)
   (assert fact1)
   (assert fact2)

   ; 5. Check satisfiability
   (check-sat)
   (get-model)
   ```

3. **Verification Semantics**
   - `sat` = True: The constraint CAN be true given the knowledge base
   - `unsat` = False: The constraint CONTRADICTS the knowledge base
   - To verify a question, assert the scenario and check satisfiability

---

### **SMT-LIB 2.0 Commands**

**Sorts (Types):**
```smt2
; Built-in sorts (no declaration needed)
Bool, Int, Real

; Uninterpreted sort
(declare-sort Person 0)

; Enumerated datatype
(declare-datatypes () ((Color (red) (green) (blue))))

; Bitvectors
(_ BitVec 8)  ; 8-bit bitvector sort
```

**Functions:**
```smt2
; Nullary function (constant)
(declare-fun age () Int)

; Unary function
(declare-fun is-politician (Person) Bool)

; Binary function
(declare-fun supports (Person Issue) Bool)
```

**Constants:**
```smt2
(declare-const nancy-pelosi Person)
(declare-const abortion Issue)
(declare-const x Int)
```

**Assertions (Knowledge Base):**
```smt2
(assert (is-politician nancy-pelosi))
(assert (= (age nancy-pelosi) 84))
(assert (> x 0))
```

**Logical Operators:**
```smt2
(and expr1 expr2 ...)   ; Conjunction
(or expr1 expr2 ...)    ; Disjunction
(not expr)              ; Negation
(=> expr1 expr2)        ; Implication
(ite cond then else)    ; If-then-else
(distinct e1 e2 ...)    ; All different
```

**Quantifiers:**
```smt2
(forall ((x Int) (y Int)) (=> (> x y) (< y x)))
(exists ((p Person)) (is-politician p))
```

**Arithmetic:**
```smt2
(+ e1 e2 ...)    ; Addition
(- e1 e2 ...)    ; Subtraction
(* e1 e2 ...)    ; Multiplication
(div e1 e2)      ; Integer division
(mod e1 e2)      ; Modulo
(= e1 e2)        ; Equality
(< e1 e2)        ; Less than
(<= e1 e2)       ; Less than or equal
(> e1 e2)        ; Greater than
(>= e1 e2)       ; Greater than or equal
```

---

### **Verification Strategy**

**CRITICAL: Create ONE Verification Per Question**

When answering a question, assert the knowledge base, then assert the scenario being tested, and finally check satisfiability.

**Question Type Strategies:**

1. **"Would/Does X do Y?" or "Is X true?"** (Factual questions)
   ```smt2
   ; Assert knowledge base
   (assert (is-politician nancy-pelosi))
   (assert (is-democrat nancy-pelosi))
   (assert (forall ((p Person) (i Issue))
     (=> (and (is-democrat p) (supports p i))
         (not (publicly-denounce p i)))))
   (assert (supports nancy-pelosi abortion))

   ; Test: Would Pelosi denounce abortion?
   (assert (publicly-denounce nancy-pelosi abortion))
   (check-sat)  ; Expected: unsat (false)
   ```

2. **"Can/Could X do Y?" or "Is it possible that X...?"** (Possibility questions)
   ```smt2
   ; Assert knowledge base
   (assert (forall ((f Animal))
     (=> (is-fish f) (can-breathe-underwater f))))

   ; Test: Can fish breathe underwater?
   (declare-const test-fish Animal)
   (assert (is-fish test-fish))
   (assert (can-breathe-underwater test-fish))
   (check-sat)  ; Expected: sat (true)
   (get-model)
   ```

3. **Comparison questions**
   ```smt2
   (declare-const genghis-khan Person)
   (declare-const julius-caesar Person)
   (declare-fun num-descendants (Person) Int)

   (assert (= (num-descendants genghis-khan) 16000000))
   (assert (= (num-descendants julius-caesar) 5000000))

   ; Test: Does Genghis Khan have more descendants?
   (assert (> (num-descendants genghis-khan)
              (num-descendants julius-caesar)))
   (check-sat)  ; Expected: sat (true)
   ```

**CRITICAL RULES:**
- ✓ **DO**: Assert knowledge base, then assert the test scenario, then `(check-sat)`
- ✓ **DO**: Use `(get-model)` after `(check-sat)` to see example values
- ✗ **DON'T**: Create multiple `(check-sat)` commands testing opposite cases
- ✗ **DON'T**: Assert both a statement and its negation

---

### **Common Patterns**

**Universal Rules:**
```smt2
(assert (forall ((p Person))
  (=> (is-law-enforcement p)
      (can-arrest p))))
```

**Existential Constraints:**
```smt2
; Use declare-const + assert instead of exists
(declare-const witness Person)
(assert (and (is-politician witness) (is-honest witness)))
(check-sat)  ; Tests if such a person can exist
```

**Implications:**
```smt2
(assert (=> (is-fish animal-x) (can-swim animal-x)))
```

**Conditional Properties:**
```smt2
(assert (forall ((p Person) (i Issue))
  (=> (supports p i)
      (not (publicly-denounce p i)))))
```

---

### **Example: Complete Program**

Question: "Would Nancy Pelosi publicly denounce abortion?"

```smt2
; Declare sorts
(declare-sort Person 0)
(declare-sort Issue 0)

; Declare functions
(declare-fun is-politician (Person) Bool)
(declare-fun is-democrat (Person) Bool)
(declare-fun supports (Person Issue) Bool)
(declare-fun publicly-denounce (Person Issue) Bool)

; Declare constants
(declare-const nancy-pelosi Person)
(declare-const abortion Issue)

; Knowledge base
(assert (is-politician nancy-pelosi))
(assert (is-democrat nancy-pelosi))

; Rule: Democrats don't denounce issues they support
(assert (forall ((p Person) (i Issue))
  (=> (and (is-democrat p) (supports p i))
      (not (publicly-denounce p i)))))

; Fact: Pelosi supports abortion rights
(assert (supports nancy-pelosi abortion))

; Test: Would she denounce it?
(assert (publicly-denounce nancy-pelosi abortion))

; Check satisfiability
(check-sat)
; Expected: unsat (she would NOT denounce it)
```

---

### **Output Format**

Your response MUST be wrapped in a markdown code block with the ```smt2``` tag:

```smt2
(declare-sort ...)
(declare-fun ...)
(assert ...)
(check-sat)
(get-model)
```

Do NOT output raw SMT2 without the markdown code block. The parser expects the SMT2 to be enclosed in ```smt2 ... ``` markers.

---

**Task:**

Think step by step and reason about the given question. Decompose the question into logical reasoning steps, declare the necessary sorts, functions, and constants, assert the knowledge base, and finally create a verification that tests the question. Ensure that:

- All declarations come before their use
- Use proper SMT-LIB 2.0 syntax
- Create EXACTLY ONE `(check-sat)` that directly answers the question
- `sat` means True, `unsat` means False

Answer the following question:

"""


def build_smt2_prompt(question: str) -> str:
    """Build the complete prompt for SMT2 program generation.

    Args:
        question: The reasoning question to answer

    Returns:
        Complete prompt string
    """
    return SMT2_INSTRUCTIONS + f"\nQuestion: {question}"
