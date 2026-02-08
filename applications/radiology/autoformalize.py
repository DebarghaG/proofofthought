"""Autoformalization of VLM radiology reports into SMT-LIB via ProofOfThought.

Takes free-text VLM output describing a chest X-ray and uses GPT-5.2 (via
the ProofOfThought Z3ProgramGenerator) to autoformalize the detected findings
into SMT-LIB assertions that can be composed with the static diagnostic
foundation and verified by Z3.

The LLM sees the foundation context (declared constants) and produces
closed-world finding assertions — each canonical finding is asserted true
or negated — as native SMT-LIB, not a JSON intermediary.

Usage:
    from openai import AzureOpenAI
    from applications.radiology.autoformalize import autoformalize_findings

    client = AzureOpenAI(...)
    result = autoformalize_findings(
        vlm_report="Focal opacity in the RLL with air bronchograms...",
        foundation_smt2=verifier._foundation_smt2,
        llm_client=client,
        model="gpt-5",
    )
    # result.smt2_assertions -> "(assert focal_opacity)\\n(assert air_bronchogram)\\n..."
    # result.detected_findings -> {"focal_opacity", "air_bronchogram"}
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from applications.radiology.verifier import DIAGNOSES, RADIOLOGY_FINDINGS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt for autoformalization
# ---------------------------------------------------------------------------

AUTOFORMALIZE_PROMPT = """\
You are a radiology-to-SMT-LIB autoformalization engine.

## Foundation Context

The following SMT-LIB foundation has already been declared. It contains:
- Bool constants for each radiological finding (e.g., `focal_opacity`, `air_bronchogram`)
- Bool constants for each diagnosis (e.g., `pneumonia_dx`, `cardiomegaly_dx`)
- Biconditional rules linking diagnoses to required finding combinations

```smt2
{foundation}
```

## Canonical Finding Names

These are ALL the declared finding constants — use ONLY these names:
{finding_names}

## Your Task

Given the VLM radiology report below, produce SMT-LIB assertions for a
**closed-world** encoding of the detected findings:

1. For each finding that the report describes as **present/detected**, emit:
   `(assert <finding_name>)`
2. For each finding that is **absent, not mentioned, or explicitly negative**, emit:
   `(assert (not <finding_name>))`
3. You MUST emit exactly one assertion for EVERY finding listed above —
   no finding may be omitted.
4. Map synonyms and descriptive language to the canonical names:
   - "opacification" / "opacity in the lobe" → `focal_opacity`
   - "blunted costophrenic angle" → `costophrenic_blunting`
   - "heart is enlarged" / "cardiac enlargement" → `enlarged_cardiac_silhouette`
   - "flattened diaphragm" → `flattened_diaphragm`
   - "hyperexpanded lungs" → `hyperinflation`
   etc.

## VLM Report

{report}

## Claimed Diagnoses (from the VLM)

{claimed_diagnoses}

## Output Format

Respond with ONLY a JSON object (no markdown fences, no other text):
{{
  "detected_findings": ["finding1", "finding2", ...],
  "claimed_diagnoses": ["diagnosis1_dx", "diagnosis2_dx", ...]
}}

Where `detected_findings` lists ONLY the findings that are positively present,
and `claimed_diagnoses` lists the diagnosis constant names the VLM claims
(mapped to the canonical `_dx` suffixed names).
"""


@dataclass
class AutoformalizationResult:
    """Result of autoformalizing a VLM report into SMT-LIB."""

    detected_findings: set[str]
    claimed_diagnoses: list[str]
    smt2_assertions: str  # SMT-LIB assertion block for findings
    prompt: str = ""  # The full prompt sent to GPT-5.2
    raw_llm_response: str = ""


def autoformalize_findings(
    vlm_report: str,
    foundation_smt2: str,
    llm_client: Any,
    model: str = "gpt-5",
    claimed_diagnoses_text: str = "",
    max_tokens: int = 4096,
    max_retries: int = 2,
) -> AutoformalizationResult:
    """Autoformalize a VLM report into SMT-LIB finding assertions.

    Uses GPT-5.2 via the OpenAI chat API to interpret the free-text VLM
    report and produce structured findings, which are then converted into
    closed-world SMT-LIB assertions.

    On parse failure, retries with feedback (appending the failed response
    and error message to the conversation) up to ``max_retries`` times.

    Args:
        vlm_report: Free-text VLM radiology report.
        foundation_smt2: The static SMT-LIB foundation (for context).
        llm_client: OpenAI-compatible client (AzureOpenAI, OpenAI, etc.).
        model: Model / deployment name.
        claimed_diagnoses_text: Free-text diagnoses claimed by the VLM.
        max_tokens: Max tokens for LLM response.
        max_retries: Number of retry attempts on parse failure.

    Returns:
        AutoformalizationResult with detected findings and SMT-LIB assertions.
    """
    finding_names_str = "\n".join(f"  - {f}" for f in RADIOLOGY_FINDINGS)

    prompt = AUTOFORMALIZE_PROMPT.format(
        foundation=foundation_smt2,
        finding_names=finding_names_str,
        report=vlm_report,
        claimed_diagnoses=claimed_diagnoses_text or "(none specified)",
    )

    messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]

    for attempt in range(1 + max_retries):
        response = llm_client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=max_tokens,
        )

        raw = response.choices[0].message.content.strip()
        logger.debug("LLM autoformalization response (attempt %d): %s", attempt + 1, raw)

        try:
            detected, claimed = _parse_llm_response(raw)
            break  # success
        except ValueError as e:
            if attempt < max_retries:
                logger.warning(
                    "Autoformalization parse failed (attempt %d/%d): %s",
                    attempt + 1, 1 + max_retries, e,
                )
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": f"Error: {e}\nRespond with ONLY valid JSON.",
                })
            else:
                raise

    # Build closed-world SMT-LIB assertions
    smt2_assertions = _build_finding_assertions(detected)

    return AutoformalizationResult(
        detected_findings=detected,
        claimed_diagnoses=claimed,
        smt2_assertions=smt2_assertions,
        prompt=prompt,
        raw_llm_response=raw,
    )


def _parse_llm_response(raw: str) -> tuple[set[str], list[str]]:
    """Parse the LLM JSON response into findings and diagnoses.

    Args:
        raw: Raw LLM response text.

    Returns:
        Tuple of (detected_findings set, claimed_diagnoses list).

    Raises:
        ValueError: If response cannot be parsed.
    """
    # Strip markdown code fences if present
    cleaned = raw
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned = "\n".join(lines)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract JSON from surrounding text
        json_match = re.search(r"\{[\s\S]*\}", cleaned)
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Failed to parse LLM response as JSON: {e}\n"
                    f"Raw response:\n{raw}"
                ) from e
        else:
            raise ValueError(
                f"No JSON found in LLM response.\nRaw response:\n{raw}"
            )

    # Extract and validate findings
    raw_findings = parsed.get("detected_findings", [])
    detected = set()
    for f in raw_findings:
        if f in RADIOLOGY_FINDINGS:
            detected.add(f)
        else:
            logger.warning("LLM returned unknown finding '%s', skipping", f)

    # Extract and validate diagnoses
    raw_diagnoses = parsed.get("claimed_diagnoses", [])
    claimed = []
    for d in raw_diagnoses:
        if d in DIAGNOSES:
            claimed.append(d)
        else:
            logger.warning("LLM returned unknown diagnosis '%s', skipping", d)

    return detected, claimed


def _build_finding_assertions(detected_findings: set[str]) -> str:
    """Build closed-world SMT-LIB assertions from detected findings.

    Every canonical finding is asserted: true if detected, negated if not.

    Args:
        detected_findings: Set of finding names that are present.

    Returns:
        SMT-LIB assertion block string.
    """
    lines = ["; --- Autoformalized findings (closed world) ---"]
    for finding in RADIOLOGY_FINDINGS:
        if finding in detected_findings:
            lines.append(f"(assert {finding})")
        else:
            lines.append(f"(assert (not {finding}))")
    return "\n".join(lines)
