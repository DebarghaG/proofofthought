# Staged SMT-LIB Autoformalization

This document describes the staged autoformalization pipeline that converts natural language text into SMT-LIB programs for formal verification.

This is now the core architecture of the product. If you want the simplest entrypoint, use `ProofOfThought.query(...)`; if you want explicit control, use the staged APIs described on this page.

## Overview

The staged autoformalization pipeline generates SMT-LIB code through multiple LLM calls, where each stage focuses on a specific aspect of the formalization:

```
Text + Question
      │
      ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   SORTS     │ ──▶ │  FUNCTIONS  │ ──▶ │  CONSTANTS  │
│ (types)     │     │ (predicates)│     │ (entities)  │
└─────────────┘     └─────────────┘     └─────────────┘
      │                                        │
      ▼                                        ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ KNOWLEDGE   │ ──▶ │  SCENARIO   │ ──▶ │   QUERY     │
│ BASE        │     │  (setup)    │     │ (check-sat) │
└─────────────┘     └─────────────┘     └─────────────┘
      │
      ▼
  SMT-LIB Program
      │
      ▼
   Z3 Solver
      │
      ▼
  sat/unsat → True/False
```

**Key Benefits:**
- **Context Preservation**: Each stage receives IR summary of what's already defined
- **Coherent Long Outputs**: LLM focuses on one aspect at a time
- **Debuggable**: Inspect each stage's output independently
- **Reusable**: Regenerate just the query stage for different questions
- **Quality Maintenance**: Smaller, focused prompts → better LLM output

## Installation

```bash
# Clone the repository
git clone https://github.com/debarghaG/proofofthought.git
cd proofofthought

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install the package
pip install -e .

# Verify installation
python -c "from proofofthought.backends.smt2 import StagedGenerator; print('OK')"
```

## Configuration

### Azure OpenAI Setup

Create a `.env` file in the project root:

```bash
# Azure OpenAI Configuration
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_KEY=your-api-key-here
AZURE_DEPLOYMENT_NAME=gpt-4o  # or gpt-5, o3, etc.
AZURE_API_VERSION=2024-12-01-preview

# For Azure AD authentication (alternative to API key)
# AZURE_USE_AD=true
```

### Standard OpenAI Setup (Alternative)

```bash
OPENAI_API_KEY=sk-your-api-key-here
```

## Quick Start

### Basic Usage

```python
import sys
sys.path.insert(0, '.')

from utils.azure_config import DEPLOYMENT_NAME, get_azure_client
from proofofthought.backends.smt2 import StagedGenerator, StagedSMT2Backend

# 1. Create LLM client wrapper
class AzureOpenAIClient:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def generate(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=4096,
        )
        return response.choices[0].message.content

# 2. Initialize generator
azure_client = get_azure_client()
llm_client = AzureOpenAIClient(azure_client, DEPLOYMENT_NAME)
generator = StagedGenerator(llm_client)

# 3. Define text and question
text = """
All humans are mortal. Socrates is a human.
"""
question = "Is Socrates mortal?"

# 4. Generate SMT-LIB
result = generator.generate(text, question)

# 5. View the generated program
print(result.smt2_program)

# 6. Execute with Z3
backend = StagedSMT2Backend()
import tempfile
with tempfile.NamedTemporaryFile(mode='w', suffix='.smt2', delete=False) as f:
    f.write(result.smt2_program)
    temp_path = f.name

verify_result = backend.execute(temp_path)
print(f"Answer: {verify_result.answer}")  # True = sat, False = unsat
```

### Using Standard OpenAI

```python
from openai import OpenAI
from proofofthought.backends.smt2 import StagedGenerator

class OpenAIClient:
    def __init__(self, model: str = "gpt-4o"):
        self.client = OpenAI()  # Uses OPENAI_API_KEY env var
        self.model = model

    def generate(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
        )
        return response.choices[0].message.content

llm_client = OpenAIClient("gpt-4o")
generator = StagedGenerator(llm_client)

result = generator.generate(
    text="All birds can fly. Penguins are birds. Penguins cannot fly.",
    question="Is there a contradiction?"
)
```

## Example: Policy Verification

```python
from proofofthought.backends.smt2 import StagedGenerator, StagedSMT2Backend

# Policy text
text = """
Changes to the spelling of the names on the ticket must be submitted
via email within 24 hours of ticket purchase. Requests submitted after
this window or through other channels (such as phone or in-person)
will not be processed.
"""

# Question to verify
question = """
I noticed my last name is misspelled on the ticket I purchased yesterday.
I'm currently in person at the airport. Can I submit the spelling change
request in person at the ticket counter?
"""

# Generate and execute
result = generator.generate(text, question)
verify_result = backend.execute_from_string(result.smt2_program)

if verify_result.answer is False:
    print("No - in-person submission violates the email-only policy")
elif verify_result.answer is True:
    print("Yes - the scenario is consistent with the rules")
else:
    print("Unknown - result is ambiguous")
```

**Expected Output:**
```
No - in-person submission violates the email-only policy
```

## Generated SMT-LIB Example

For the policy verification example above, the staged generator produces:

```smt2
(set-logic ALL)

; --- Sorts ---
(declare-sort Ticket 0)
(declare-sort Request 0)

; --- Functions ---
(declare-fun purchase_time (Ticket) Int)
(declare-fun submission_time (Request) Int)
(declare-fun submitted_via_email (Request) Bool)
(declare-fun submitted_in_person (Request) Bool)
(declare-fun spelling_change_request (Request Ticket) Bool)

; --- Constants ---
(declare-const t0 Ticket)
(declare-const r0 Request)

; --- Knowledge Base ---
; Rule: spelling changes must be via email within 24 hours
(assert (forall ((t Ticket) (r Request))
  (=> (spelling_change_request r t)
      (and
        (submitted_via_email r)
        (<= (- (submission_time r) (purchase_time t)) 86400)))))

; In-person means not via email
(assert (forall ((r Request))
  (=> (submitted_in_person r) (not (submitted_via_email r)))))

; --- Scenario ---
; This is a spelling change request
(assert (spelling_change_request r0 t0))
; Submitted in person
(assert (submitted_in_person r0))

; --- Query ---
(check-sat)
; Result: unsat (scenario contradicts the rules)
```

## API Reference

### StagedGenerator

```python
class StagedGenerator:
    def __init__(self, llm_client: LLMClient) -> None:
        """
        Initialize the staged generator.

        Args:
            llm_client: Any object with a generate(prompt: str) -> str method
        """

    def generate(
        self,
        text: str,
        question: str,
        stages: list[str] | None = None,
    ) -> GenerationResult:
        """
        Generate SMT-LIB through staged prompting.

        Args:
            text: Natural language describing the domain/rules
            question: The question to verify
            stages: Optional subset of stages to run
                    (default: all stages)

        Returns:
            GenerationResult with:
              - smt2_program: Complete SMT-LIB program
              - context: ConversionContext (IR)
              - stage_outputs: Dict of each stage's output
              - errors: List of any errors encountered
        """

    def get_context(self) -> ConversionContext:
        """Get the current conversion context (IR)."""

    def get_context_summary(self) -> str:
        """Get human-readable summary of what's been generated."""
```

### GenerationResult

```python
@dataclass
class GenerationResult:
    success: bool              # True if all stages completed
    smt2_program: str          # Complete SMT-LIB program
    context: ConversionContext # IR tracking all conversions
    stage_outputs: dict[str, str]  # Output from each stage
    errors: list[str]          # Any errors encountered
```

### ConversionContext (IR)

```python
@dataclass
class ConversionContext:
    logic: str                           # SMT-LIB logic (default: "ALL")
    sorts: dict[str, SMTSort]           # Defined sorts
    functions: dict[str, SMTFunction]   # Defined functions
    constants: dict[str, SMTConstant]   # Defined constants
    variables: dict[str, str]           # Free variables (name -> sort)
    kb_assertions: dict[str, SMTAssertion]  # Knowledge base
    queries: dict[str, SMTQuery]        # Verification queries

    def to_summary(self) -> str:
        """Generate summary for LLM context."""

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
```

### StagedSMT2Backend

```python
class StagedSMT2Backend:
    def __init__(
        self,
        verify_timeout: int = 10000,  # milliseconds
        z3_path: str = "z3",
    ) -> None:
        """Initialize the backend."""

    def execute(self, program_path: str) -> VerificationResult:
        """Execute an SMT-LIB file via Z3."""

    def execute_config(
        self,
        config: dict,
    ) -> tuple[VerificationResult, ExecutionResult]:
        """Execute a DSL config through the pipeline."""

    def generate_smt2(self, config: dict) -> str:
        """Generate SMT-LIB without executing."""

    def build_foundation(
        self,
        config: dict,
        through_stage: str = "rules",
    ) -> str:
        """Build reusable foundation (sorts, functions, KB)."""

    def add_query(
        self,
        verification: dict,
        foundation: str | None = None,
    ) -> str:
        """Add a query on top of existing foundation."""
```

## Pipeline Stages

| Stage | Purpose | SMT-LIB Output |
|-------|---------|----------------|
| `sorts` | Define entity types | `(declare-sort ...)` |
| `functions` | Define predicates/functions | `(declare-fun ...)` |
| `constants` | Define specific entities | `(declare-const ...)` |
| `knowledge_base` | Encode facts and rules | `(assert ...)` |
| `scenario` | Set up the specific test case | `(assert ...)` |
| `query` | Formulate verification | `(check-sat)` |

### Running Specific Stages

```python
# Run only sorts and functions
result = generator.generate(
    text,
    question,
    stages=["sorts", "functions"]
)

# The result will contain partial SMT-LIB
print(result.smt2_program)
```

## Interpreting Results

| Z3 Result | Meaning | Answer |
|-----------|---------|--------|
| `sat` | Scenario is **consistent** with the rules | `True` |
| `unsat` | Scenario **contradicts** the rules | `False` |
| `unknown` | Solver couldn't determine | `None` |

**Important**: The interpretation depends on how you frame the question:
- "Can X happen?" → sat means yes, unsat means no
- "Is X impossible?" → sat means no (it's possible), unsat means yes

## Debugging

### View Stage Outputs

```python
result = generator.generate(text, question)

for stage_name, output in result.stage_outputs.items():
    print(f"=== {stage_name.upper()} ===")
    print(output)
    print()
```

### View Conversion Context

```python
ctx = result.context

print(f"Sorts: {list(ctx.sorts.keys())}")
print(f"Functions: {list(ctx.functions.keys())}")
print(f"Constants: {list(ctx.constants.keys())}")
print(f"KB assertions: {len(ctx.kb_assertions)}")
```

### Check for Errors

```python
if result.errors:
    print("Errors occurred:")
    for error in result.errors:
        print(f"  - {error}")
```

## Troubleshooting

### Common Issues

**1. Azure Authentication Error (403)**
```
Error code: 403 - {'error': {'code': 'AuthenticationTypeDisabled'...}}
```
Solution: Enable key-based authentication on your Azure OpenAI resource, or use Azure AD auth (`az login`).

**2. Z3 Not Found**
```
FileNotFoundError: Z3 executable not found
```
Solution: Install Z3 solver:
```bash
pip install z3-solver
# Or on macOS: brew install z3
```

**3. Empty Output from Stage**
Check that your text contains enough information for the stage. The LLM needs clear entities, relationships, and rules to formalize.

**4. Incorrect sat/unsat Result**
- Review the generated SMT-LIB to ensure correct encoding
- Check if the question framing matches your interpretation
- Verify the knowledge base captures all relevant rules

## Advanced Usage

### Custom LLM Client

Implement any LLM by providing a `generate(prompt: str) -> str` method:

```python
class CustomLLMClient:
    def generate(self, prompt: str) -> str:
        # Your LLM API call here
        return response_text

generator = StagedGenerator(CustomLLMClient())
```

### Reusing Foundations

Generate a foundation once, then add multiple queries:

```python
# Build foundation with sorts, functions, and KB
foundation = backend.build_foundation(config, through_stage="rules")

# Add different queries
query1 = backend.add_query({"name": "q1", "constraint": "..."}, foundation)
query2 = backend.add_query({"name": "q2", "constraint": "..."}, foundation)

# Execute each
result1 = backend.execute_from_string(query1)
result2 = backend.execute_from_string(query2)
```

### Accessing Raw Prompts

```python
from proofofthought.backends.smt2 import (
    format_sorts_prompt,
    format_functions_prompt,
    format_kb_prompt,
    ConversionContext,
)

ctx = ConversionContext()
prompt = format_sorts_prompt("Your text here", ctx)
print(prompt)
```

## Running the Example Script

```bash
# Activate virtual environment
source venv/bin/activate

# Set up your .env file with Azure credentials

# Run the example
python examples/staged_autoformalization.py

# Or run the simple example
python examples/staged_autoformalization.py --simple
```
