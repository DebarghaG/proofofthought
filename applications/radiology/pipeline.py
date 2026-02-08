"""Logged radiology verification pipeline.

Orchestrates the full flow and writes every intermediate artifact to a
timestamped log directory:

    logs/run_YYYYMMDD_HHMMSS/
        00_clinical_decision_procedure.txt      # Human-readable rules
        00_foundation.smt2                       # Static SMT-LIB foundation
        01_classic_lobar_pneumonia/
            01_vlm_report.txt                    # Simulated VLM text
            02_autoformalize_prompt.txt           # Full prompt sent to GPT-5.2
            03_autoformalize_response.json        # GPT-5.2 raw response
            04_detected_findings.json             # Parsed findings + diagnoses
            05_finding_assertions.smt2            # Closed-world SMT-LIB assertions
            06_verify_pneumonia_dx.smt2           # Composed program for Z3
            06_verify_pneumonia_dx.z3out          # Z3 raw output
            ...                                   # One pair per diagnosis
            07_report.json                        # Final verification report
        ...
        summary.json                             # Aggregate results
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from applications.radiology.autoformalize import (
    AutoformalizationResult,
    autoformalize_findings,
)
from applications.radiology.verifier import (
    DIAGNOSES,
    DIAGNOSTIC_RULES,
    DIAGNOSIS_LABELS,
    RADIOLOGY_FINDINGS,
    RadiologyVerifier,
    VerificationReport,
)


def _slugify(name: str) -> str:
    """Convert a case name to a filesystem-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower())
    return slug.strip("_")


def _clinical_decision_procedure_text() -> str:
    """Render the diagnostic rules as human-readable text."""
    lines = [
        "CLINICAL DECISION PROCEDURE",
        "=" * 60,
        "",
        "Each diagnosis is a biconditional: the diagnosis holds if and only",
        "if the required combination of radiological findings is met.",
        "",
    ]
    for dx, expr in DIAGNOSTIC_RULES.items():
        label = DIAGNOSIS_LABELS[dx]
        lines.append(f"  {label} ({dx})")
        lines.append(f"    Criteria: {expr}")
        lines.append("")

    lines.append("-" * 60)
    lines.append(f"Total findings: {len(RADIOLOGY_FINDINGS)}")
    lines.append(f"Total diagnoses: {len(DIAGNOSES)}")
    lines.append("")
    lines.append("Findings:")
    for f in RADIOLOGY_FINDINGS:
        lines.append(f"  - {f}")
    return "\n".join(lines)


def _report_to_dict(report: VerificationReport) -> dict[str, Any]:
    """Serialize a VerificationReport to a JSON-safe dict."""
    return {
        "detected_findings": sorted(report.detected_findings),
        "claimed_diagnoses": report.claimed_diagnoses,
        "supported": report.supported,
        "unsupported": report.unsupported,
        "missed": report.missed,
        "per_diagnosis": {
            dx: {
                "label": r.label,
                "entailed": r.entailed,
                "z3_status": r.z3_status,
            }
            for dx, r in report.results.items()
        },
    }


def run_pipeline(
    cases: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    log_dir: str | Path | None = None,
    z3_path: str | None = None,
) -> Path:
    """Run the full pipeline for a list of VLM cases with comprehensive logging.

    Args:
        cases: List of dicts with keys: name, vlm_text, claimed_diagnoses_text.
        llm_client: OpenAI-compatible client.
        model: Model / deployment name.
        log_dir: Root log directory (default: applications/radiology/logs/).
        z3_path: Path to Z3 executable (auto-detected if None).

    Returns:
        Path to the run directory containing all log files.
    """
    # Set up log directory
    if log_dir is None:
        log_dir = Path(__file__).parent / "logs"
    log_dir = Path(log_dir)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = log_dir / f"run_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # ---- Step 0: Write the static foundation ----

    verifier = RadiologyVerifier(z3_path=z3_path)

    (run_dir / "00_clinical_decision_procedure.txt").write_text(
        _clinical_decision_procedure_text()
    )
    (run_dir / "00_foundation.smt2").write_text(verifier._foundation_smt2)

    # ---- Process each case ----

    summaries: list[dict[str, Any]] = []

    for i, case in enumerate(cases, start=1):
        case_name = case["name"]
        vlm_text = case["vlm_text"]
        claimed_text = case.get("claimed_diagnoses_text", "")

        case_slug = f"{i:02d}_{_slugify(case_name)}"
        case_dir = run_dir / case_slug
        case_dir.mkdir(parents=True, exist_ok=True)

        # ---- 1. VLM report ----
        (case_dir / "01_vlm_report.txt").write_text(vlm_text)

        # ---- 2-5. Autoformalize via GPT-5.2 ----
        af_result = autoformalize_findings(
            vlm_report=vlm_text,
            foundation_smt2=verifier._foundation_smt2,
            llm_client=llm_client,
            model=model,
            claimed_diagnoses_text=claimed_text,
        )

        (case_dir / "02_autoformalize_prompt.txt").write_text(af_result.prompt)
        (case_dir / "03_autoformalize_response.json").write_text(
            af_result.raw_llm_response
        )
        (case_dir / "04_detected_findings.json").write_text(
            json.dumps(
                {
                    "detected_findings": sorted(af_result.detected_findings),
                    "claimed_diagnoses": af_result.claimed_diagnoses,
                },
                indent=2,
            )
        )
        (case_dir / "05_finding_assertions.smt2").write_text(
            af_result.smt2_assertions
        )

        # ---- 6. Verify each diagnosis ----
        report = verifier.verify_all(
            detected_findings=af_result.detected_findings,
            claimed_diagnoses=af_result.claimed_diagnoses,
        )

        for dx in DIAGNOSES:
            dr = report.results[dx]
            (case_dir / f"06_verify_{dx}.smt2").write_text(dr.smt2_program)
            (case_dir / f"06_verify_{dx}.z3out").write_text(dr.raw_output)

        # ---- 7. Final report ----
        report_dict = _report_to_dict(report)
        (case_dir / "07_report.json").write_text(
            json.dumps(report_dict, indent=2)
        )

        summaries.append(
            {
                "case": case_name,
                "dir": case_slug,
                **report_dict,
            }
        )

    # ---- Summary ----
    total_s = sum(len(s["supported"]) for s in summaries)
    total_u = sum(len(s["unsupported"]) for s in summaries)
    total_m = sum(len(s["missed"]) for s in summaries)

    summary = {
        "timestamp": timestamp,
        "model": model,
        "num_cases": len(cases),
        "total_supported": total_s,
        "total_unsupported": total_u,
        "total_missed": total_m,
        "cases": summaries,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    return run_dir
