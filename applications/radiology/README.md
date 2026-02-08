# Radiology Diagnostic Verification

Verifies whether a VLM's claimed diagnoses are logically entailed by detected radiological findings, using Z3 as a formal verification backend.

**Pipeline:** VLM report (free text) → GPT-5.2 autoformalization → SMT-LIB → Z3

## Prerequisites

- Z3 solver installed (`pip install z3-solver` or [binary release](https://github.com/Z3Prover/z3/releases))
- Azure OpenAI credentials in `.env` at project root (see `.env.example`). Not needed for `--mock` mode.

## Running

```bash
# Mock mode — hardcoded findings, no LLM call, just Z3
python -m applications.radiology.demo --mock

# Full pipeline — GPT-5.2 autoformalization + Z3 verification
python -m applications.radiology.demo
```

Artifacts are logged to `applications/radiology/logs/run_<timestamp>/`.

## Tests

```bash
# Unit tests (Z3 required, no LLM)
python -m pytest applications/radiology/test_verifier.py -v

# Full pipeline tests — 15 VLM cases through GPT-5.2 + Z3
python -m pytest applications/radiology/test_vlm_cases.py -v -s
```
