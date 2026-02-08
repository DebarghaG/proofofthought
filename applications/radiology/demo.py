"""End-to-end radiology diagnostic verification demo.

Full pipeline:
1. Build the RadiologyVerifier (static SMT-LIB foundation, once).
2. Simulate a VLM report (free text).
3. Autoformalize findings via GPT-5.2 — LLM reads the VLM text + foundation
   context and produces structured findings that become SMT-LIB assertions.
4. Compose foundation + autoformalized assertions + entailment queries → Z3.
5. Report: which diagnoses are supported, unsupported, or missed.

All intermediate artifacts are logged to a timestamped directory.

Run:
    python -m applications.radiology.demo          # with Azure OpenAI GPT-5.2
    python -m applications.radiology.demo --mock    # with hardcoded findings
"""

from __future__ import annotations

import argparse
import json
import sys

from applications.radiology.pipeline import run_pipeline
from applications.radiology.verifier import (
    DIAGNOSIS_LABELS,
    RadiologyVerifier,
)

# ---------------------------------------------------------------------------
# Sample VLM report
# ---------------------------------------------------------------------------

SAMPLE_VLM_REPORT = (
    "PA chest radiograph. There is a dense area of opacification in the "
    "right lower lobe with prominent air bronchograms. The cardiac silhouette "
    "is markedly enlarged. Blunting of the right costophrenic angle suggests "
    "a small pleural effusion. No pneumothorax is identified. Lung volumes "
    "are normal. No fractures. "
    "Impression: right lower lobe pneumonia, cardiomegaly, small right "
    "pleural effusion."
)

SAMPLE_CLAIMED_TEXT = "Pneumonia, Cardiomegaly"

# For --mock mode: ground-truth findings (bypass LLM)
MOCK_FINDINGS = {
    "dense_opacity",
    "air_bronchogram",
    "enlarged_cardiac_silhouette",
    "costophrenic_blunting",
}
MOCK_DIAGNOSES = ["pneumonia_dx", "cardiomegaly_dx"]


def run_demo(*, use_mock: bool = False, z3_path: str | None = None) -> None:
    """Run the end-to-end demo."""
    print("=" * 64)
    print("  Radiology Diagnostic Verification Demo")
    print("  Pipeline: VLM text -> GPT-5.2 autoformalize -> SMT-LIB -> Z3")
    print("=" * 64)

    if use_mock:
        # Mock mode: bypass LLM, use hardcoded findings
        print("\n[mock] Using hardcoded findings (--mock mode, no LLM call).")
        print(f"\n  Simulated VLM report:")
        print(f"    \"{SAMPLE_VLM_REPORT}\"")

        verifier = RadiologyVerifier(z3_path=z3_path)
        detected = MOCK_FINDINGS
        claimed = MOCK_DIAGNOSES

        print(f"    Detected findings: {sorted(detected)}")
        print(f"    Claimed diagnoses: {claimed}")

        report = verifier.verify_all(
            detected_findings=detected,
            claimed_diagnoses=claimed,
        )

        _print_report(report, claimed)
    else:
        # Full pipeline with logging
        print("\n[1] Running full logged pipeline via GPT-5.2 ...")
        from utils.azure_config import get_azure_client, DEPLOYMENT_NAME

        client = get_azure_client()
        cases = [
            {
                "name": "Demo case",
                "vlm_text": SAMPLE_VLM_REPORT,
                "claimed_diagnoses_text": SAMPLE_CLAIMED_TEXT,
            }
        ]

        run_dir = run_pipeline(
            cases=cases,
            llm_client=client,
            model=DEPLOYMENT_NAME,
            z3_path=z3_path,
        )

        # Read back summary
        summary = json.loads((run_dir / "summary.json").read_text())
        case_result = summary["cases"][0]

        print(f"\n  Detected findings: {case_result['detected_findings']}")
        print(f"  Claimed diagnoses: {case_result['claimed_diagnoses']}")

        print("\n" + "=" * 64)
        print("  Verification Results")
        print("=" * 64)

        for dx, info in case_result["per_diagnosis"].items():
            if dx in case_result["supported"]:
                print(f"    + {info['label']:<20s}  [SUPPORTED]  (Z3: {info['z3_status']})")
            elif dx in case_result["unsupported"]:
                print(f"    - {info['label']:<20s}  [NOT SUPPORTED]  (Z3: {info['z3_status']})")

        if case_result["missed"]:
            print(f"\n  Missed diagnoses ({len(case_result['missed'])}):")
            for dx in case_result["missed"]:
                print(f"    ! {DIAGNOSIS_LABELS.get(dx, dx)}")
        else:
            print("\n  No missed diagnoses.")

        print(f"\n  All artifacts logged to: {run_dir}")
        print()


def _print_report(report, claimed):
    """Print verification results (mock mode)."""
    print("\n" + "=" * 64)
    print("  Verification Results")
    print("=" * 64)

    print("\n  Claimed diagnoses:")
    for dx in claimed:
        r = report.results[dx]
        status = "SUPPORTED" if r.entailed else "NOT SUPPORTED"
        print(f"    {r.label:<20s}  [{status}]  (Z3: {r.z3_status})")

    if report.supported:
        print(f"\n  Supported ({len(report.supported)}):")
        for dx in report.supported:
            print(f"    + {DIAGNOSIS_LABELS[dx]}")

    if report.unsupported:
        print(f"\n  Not supported ({len(report.unsupported)}):")
        for dx in report.unsupported:
            print(f"    - {DIAGNOSIS_LABELS[dx]}")

    if report.missed:
        print(f"\n  Missed diagnoses ({len(report.missed)}):")
        for dx in report.missed:
            print(f"    ! {DIAGNOSIS_LABELS[dx]}")
    else:
        print("\n  No missed diagnoses.")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Radiology verification demo")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use hardcoded findings instead of calling GPT-5.2",
    )
    parser.add_argument(
        "--z3-path",
        default=None,
        help="Path to Z3 executable (auto-detected from venv by default)",
    )
    args = parser.parse_args()

    try:
        run_demo(use_mock=args.mock, z3_path=args.z3_path)
    except FileNotFoundError as e:
        print(f"\nError: {e}", file=sys.stderr)
        print("Install Z3 or pass --z3-path /path/to/z3", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
