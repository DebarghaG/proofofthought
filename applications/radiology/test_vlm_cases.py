"""Full-pipeline VLM radiology case verification with artifact logging.

Each case provides a simulated VLM free-text radiology report (the mock part).
The report is sent through GPT-5.2 autoformalization to extract structured
findings as SMT-LIB assertions, which are then verified against the diagnostic
rules via Z3.

Pipeline per case:
    VLM text (mock) → GPT-5.2 autoformalize → SMT-LIB assertions → Z3 verify

All intermediate artifacts are written to a timestamped log directory via
the logged pipeline (``applications.radiology.pipeline``).

Run:
    python -m pytest applications/radiology/test_vlm_cases.py -v -s
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from applications.radiology.autoformalize import (
    AutoformalizationResult,
    autoformalize_findings,
)
from applications.radiology.pipeline import run_pipeline
from applications.radiology.verifier import (
    DIAGNOSIS_LABELS,
    RadiologyVerifier,
    VerificationReport,
)


# ---------------------------------------------------------------------------
# Case definition
# ---------------------------------------------------------------------------

@dataclass
class VLMCase:
    """A simulated VLM radiology case."""

    name: str
    vlm_text: str  # Free-text report as a VLM would produce
    claimed_diagnoses_text: str  # Free-text diagnosis impression from VLM
    # Expected outcomes (for assertion)
    expect_supported: list[str] = field(default_factory=list)
    expect_unsupported: list[str] = field(default_factory=list)
    expect_missed: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 15 simulated VLM reports
# ---------------------------------------------------------------------------

VLM_CASES: list[VLMCase] = [
    # 1. Classic lobar pneumonia
    VLMCase(
        name="Classic lobar pneumonia",
        vlm_text=(
            "PA chest radiograph. There is a dense area of opacification in "
            "the right lower lobe with prominent air bronchograms extending "
            "through the consolidated region. The left lung is clear. No "
            "pleural effusions bilaterally. Heart size appears normal. Bony "
            "structures are intact without fracture."
        ),
        claimed_diagnoses_text="Pneumonia",
        expect_supported=["pneumonia_dx"],
        expect_missed=["consolidation_dx"],
    ),

    # 2. Tension pneumothorax
    VLMCase(
        name="Tension pneumothorax",
        vlm_text=(
            "Supine AP chest X-ray. A thin visceral pleural line is visible "
            "along the left hemithorax with complete absence of lung markings "
            "laterally. Deep sulcus sign present on the left. Mediastinal "
            "shift to the right is noted. Heart size is obscured. No rib "
            "fractures identified."
        ),
        claimed_diagnoses_text="Left tension pneumothorax",
        expect_supported=["pneumothorax_dx"],
    ),

    # 3. Congestive heart failure — edema + cardiomegaly + effusion
    VLMCase(
        name="Congestive heart failure",
        vlm_text=(
            "PA and lateral chest radiographs. The cardiac silhouette is "
            "significantly enlarged with a cardiothoracic ratio exceeding 0.6. "
            "Bilateral perihilar infiltrates are present with cephalization of "
            "the pulmonary vasculature. Blunting of both costophrenic angles "
            "consistent with bilateral pleural effusions. No pneumothorax. "
            "Impression: pulmonary edema with cardiomegaly and bilateral "
            "effusions."
        ),
        claimed_diagnoses_text="Pulmonary edema, Cardiomegaly",
        expect_supported=["pulmonary_edema_dx", "cardiomegaly_dx"],
        expect_missed=["pleural_effusion_dx"],
    ),

    # 4. Isolated rib fracture
    VLMCase(
        name="Isolated rib fracture",
        vlm_text=(
            "Dedicated rib series and chest X-ray. A cortical break is "
            "identified through the lateral cortex of the right 7th rib with "
            "mild displacement. No pneumothorax. Lungs are clear bilaterally. "
            "Heart size is normal. No pleural fluid."
        ),
        claimed_diagnoses_text="Right 7th rib fracture",
        expect_supported=["fracture_dx"],
    ),

    # 5. VLM hallucinates pneumonia — no air bronchograms
    VLMCase(
        name="False pneumonia (no air bronchograms)",
        vlm_text=(
            "PA chest X-ray. There is a subtle focal opacity in the left "
            "lower lobe. No air bronchograms are identified within the "
            "opacity. The finding may represent atelectasis versus early "
            "infiltrate. Heart size normal. No effusion. "
            "Impression: possible early pneumonia."
        ),
        claimed_diagnoses_text="Pneumonia",
        expect_unsupported=["pneumonia_dx"],
    ),

    # 6. Large pleural effusion
    VLMCase(
        name="Large pleural effusion",
        vlm_text=(
            "PA chest film. There is a large left-sided pleural effusion with "
            "a classic meniscus sign. On the left lateral decubitus view, the "
            "fluid is freely layering. Blunting of the left costophrenic "
            "angle. The right lung is clear. Heart size is difficult to "
            "assess due to the effusion."
        ),
        claimed_diagnoses_text="Left pleural effusion",
        expect_supported=["pleural_effusion_dx"],
    ),

    # 7. Severe emphysema
    VLMCase(
        name="Severe emphysema",
        vlm_text=(
            "PA and lateral chest X-ray. The lungs are markedly hyperinflated "
            "with flattening of both hemidiaphragms. Multiple bullae are "
            "identified in the upper lobes bilaterally. The retrosternal "
            "airspace is increased. Heart appears small — likely due to "
            "hyperinflation. No consolidation, effusion, or fracture."
        ),
        claimed_diagnoses_text="Emphysema",
        expect_supported=["emphysema_dx"],
    ),

    # 8. Pulmonary fibrosis (UIP pattern)
    VLMCase(
        name="Pulmonary fibrosis (UIP)",
        vlm_text=(
            "High-resolution CT correlation available. Chest X-ray shows "
            "bilateral basal reticular opacities with a honeycombing pattern "
            "in the lower lobes. Traction bronchiectasis is noted. There is "
            "associated volume loss with elevated hemidiaphragms. Heart size "
            "is within normal limits. No effusion."
        ),
        claimed_diagnoses_text="Pulmonary fibrosis (UIP pattern)",
        expect_supported=["fibrosis_dx"],
    ),

    # 9. Post-operative atelectasis
    VLMCase(
        name="Post-operative atelectasis",
        vlm_text=(
            "Portable AP chest radiograph, post-operative day 2. Linear "
            "opacities are seen at the left base with volume loss and "
            "elevation of the left hemidiaphragm. Minor displacement of the "
            "left major fissure is noted. No pneumothorax. Heart size is "
            "normal. Endotracheal tube in satisfactory position."
        ),
        claimed_diagnoses_text="Left basilar atelectasis",
        expect_supported=["atelectasis_dx"],
    ),

    # 10. Normal CXR — VLM wrongly claims cardiomegaly
    VLMCase(
        name="Normal CXR with false cardiomegaly",
        vlm_text=(
            "PA chest radiograph. The heart size is at the upper limits of "
            "normal. Lungs are clear without focal consolidation, effusion, "
            "or pneumothorax. Mediastinal contours are normal. Bony "
            "structures are intact. "
            "Impression: borderline cardiomegaly."
        ),
        claimed_diagnoses_text="Cardiomegaly",
        expect_unsupported=["cardiomegaly_dx"],
    ),

    # 11. Pneumonia with parapneumonic effusion
    VLMCase(
        name="Pneumonia with parapneumonic effusion",
        vlm_text=(
            "PA chest X-ray. Dense consolidation occupying the right middle "
            "and lower lobes with air bronchograms throughout the opacified "
            "region. Right costophrenic angle is blunted, consistent with a "
            "moderate parapneumonic effusion. Left lung is clear. Heart size "
            "normal. No rib fractures."
        ),
        claimed_diagnoses_text="Pneumonia, right pleural effusion",
        expect_supported=["pneumonia_dx", "pleural_effusion_dx"],
        expect_missed=["consolidation_dx"],
    ),

    # 12. Ground-glass pneumonia (COVID pattern)
    VLMCase(
        name="Ground-glass pneumonia (COVID)",
        vlm_text=(
            "Portable AP chest radiograph. Bilateral peripheral ground-glass "
            "opacities are present, predominantly in the lower lobes. Subtle "
            "air bronchograms are visible within the opacified areas. No "
            "pleural effusion or pneumothorax. Heart size normal. Clinical "
            "context: COVID-19 positive."
        ),
        claimed_diagnoses_text="Viral pneumonia",
        expect_supported=["pneumonia_dx"],
    ),

    # 13. Fracture with missed pneumothorax
    VLMCase(
        name="Fracture with occult pneumothorax",
        vlm_text=(
            "Chest X-ray following trauma. Cortical break identified at the "
            "left 5th rib anteriorly. On close inspection, a thin visceral "
            "pleural line is visible at the left apex — this may have been "
            "missed on initial read. No effusion. Heart size normal. "
            "Impression: left rib fracture."
        ),
        claimed_diagnoses_text="Rib fracture",
        expect_supported=["fracture_dx"],
        expect_missed=["pneumothorax_dx"],
    ),

    # 14. Non-cardiogenic pulmonary edema (ARDS)
    VLMCase(
        name="ARDS (non-cardiogenic pulmonary edema)",
        vlm_text=(
            "Portable AP chest film in the ICU. Diffuse bilateral opacities "
            "are present with peribronchial cuffing and Kerley B lines at "
            "the lung bases. Heart size is within normal limits — not "
            "enlarged. No pleural effusion. Clinical context: sepsis. "
            "Impression: ARDS / non-cardiogenic pulmonary edema."
        ),
        claimed_diagnoses_text="Pulmonary edema",
        expect_supported=["pulmonary_edema_dx"],
    ),

    # 15. Multi-pathology ICU patient
    VLMCase(
        name="Multi-pathology ICU patient",
        vlm_text=(
            "Portable AP chest radiograph. The cardiac silhouette is severely "
            "enlarged. Bilateral infiltrates with upper lobe cephalization "
            "and Kerley B lines indicate pulmonary edema. Dense opacification "
            "in the right middle lobe with air bronchograms suggests "
            "superimposed pneumonia or consolidation. Left costophrenic angle "
            "is blunted, indicating a left pleural effusion. A cortical break "
            "is seen at the right clavicle. "
            "Impression: cardiomegaly, pulmonary edema, RML pneumonia, left "
            "pleural effusion, clavicle fracture."
        ),
        claimed_diagnoses_text=(
            "Cardiomegaly, pulmonary edema, pneumonia, "
            "pleural effusion, fracture"
        ),
        expect_supported=[
            "cardiomegaly_dx",
            "pulmonary_edema_dx",
            "pneumonia_dx",
            "pleural_effusion_dx",
            "fracture_dx",
        ],
        expect_missed=["consolidation_dx"],
    ),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def azure_client():
    """Get Azure OpenAI client + deployment name."""
    try:
        from utils.azure_config import get_azure_client, DEPLOYMENT_NAME
        client = get_azure_client()
        return client, DEPLOYMENT_NAME
    except Exception as e:
        pytest.skip(f"Azure OpenAI not configured: {e}")


@pytest.fixture(scope="module")
def pipeline_run(azure_client, tmp_path_factory):
    """Run the full logged pipeline once for all 15 cases.

    Returns (run_dir, results) where results maps case name →
    (AutoformalizationResult-like dict, VerificationReport-like dict).
    """
    client, model = azure_client

    log_dir = tmp_path_factory.mktemp("radiology_logs")
    cases_for_pipeline = [
        {
            "name": case.name,
            "vlm_text": case.vlm_text,
            "claimed_diagnoses_text": case.claimed_diagnoses_text,
        }
        for case in VLM_CASES
    ]

    try:
        run_dir = run_pipeline(
            cases=cases_for_pipeline,
            llm_client=client,
            model=model,
            log_dir=log_dir,
        )
    except FileNotFoundError:
        pytest.skip("Z3 not installed")

    # Read back the summary for quick test access
    summary = json.loads((run_dir / "summary.json").read_text())

    return run_dir, summary


@pytest.fixture(scope="module")
def autoformalized_cases(pipeline_run):
    """Extract per-case results from the pipeline run for assertion tests."""
    run_dir, summary = pipeline_run

    results: dict[str, VerificationReport] = {}
    for case_summary in summary["cases"]:
        name = case_summary["case"]
        report = VerificationReport(
            detected_findings=set(case_summary["detected_findings"]),
            claimed_diagnoses=case_summary["claimed_diagnoses"],
        )
        report.supported = case_summary["supported"]
        report.unsupported = case_summary["unsupported"]
        report.missed = case_summary["missed"]
        # Populate per-diagnosis results from the report JSON
        for dx, info in case_summary["per_diagnosis"].items():
            from applications.radiology.verifier import DiagnosisResult
            report.results[dx] = DiagnosisResult(
                diagnosis=dx,
                label=info["label"],
                entailed=info["entailed"],
                z3_status=info["z3_status"],
            )
        results[name] = report

    return results


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", VLM_CASES, ids=[c.name for c in VLM_CASES])
class TestVLMPipeline:
    """Full pipeline: VLM text → GPT-5.2 → SMT-LIB → Z3."""

    def test_supported(self, autoformalized_cases, case: VLMCase):
        report = autoformalized_cases[case.name]
        for dx in case.expect_supported:
            label = DIAGNOSIS_LABELS.get(dx, dx)
            assert dx in report.supported, (
                f"[{case.name}] Expected {label} SUPPORTED.\n"
                f"  Autoformalized findings: {sorted(report.detected_findings)}\n"
                f"  Z3 status: {report.results[dx].z3_status}\n"
                f"  Supported: {report.supported}\n"
                f"  Unsupported: {report.unsupported}"
            )

    def test_unsupported(self, autoformalized_cases, case: VLMCase):
        report = autoformalized_cases[case.name]
        for dx in case.expect_unsupported:
            label = DIAGNOSIS_LABELS.get(dx, dx)
            assert dx in report.unsupported, (
                f"[{case.name}] Expected {label} UNSUPPORTED.\n"
                f"  Autoformalized findings: {sorted(report.detected_findings)}\n"
                f"  Z3 status: {report.results[dx].z3_status}"
            )

    def test_missed(self, autoformalized_cases, case: VLMCase):
        report = autoformalized_cases[case.name]
        for dx in case.expect_missed:
            label = DIAGNOSIS_LABELS.get(dx, dx)
            assert dx in report.missed, (
                f"[{case.name}] Expected {label} MISSED.\n"
                f"  Autoformalized findings: {sorted(report.detected_findings)}\n"
                f"  Z3 status: {report.results[dx].z3_status}"
            )


# ---------------------------------------------------------------------------
# Log artifact verification
# ---------------------------------------------------------------------------

class TestLogArtifacts:
    """Verify that the pipeline writes all expected log files."""

    def test_foundation_files(self, pipeline_run):
        run_dir, _ = pipeline_run
        assert (run_dir / "00_clinical_decision_procedure.txt").is_file()
        assert (run_dir / "00_foundation.smt2").is_file()
        # Foundation should contain declare-const
        foundation = (run_dir / "00_foundation.smt2").read_text()
        assert "declare-const" in foundation

    def test_summary_json(self, pipeline_run):
        run_dir, summary = pipeline_run
        assert (run_dir / "summary.json").is_file()
        assert summary["num_cases"] == len(VLM_CASES)
        assert len(summary["cases"]) == len(VLM_CASES)

    def test_case_directories_exist(self, pipeline_run):
        run_dir, summary = pipeline_run
        for case_info in summary["cases"]:
            case_dir = run_dir / case_info["dir"]
            assert case_dir.is_dir(), f"Missing case directory: {case_info['dir']}"

    def test_case_artifacts_complete(self, pipeline_run):
        """Each case dir has all 7 artifact types."""
        run_dir, summary = pipeline_run
        for case_info in summary["cases"]:
            case_dir = run_dir / case_info["dir"]
            assert (case_dir / "01_vlm_report.txt").is_file()
            assert (case_dir / "02_autoformalize_prompt.txt").is_file()
            assert (case_dir / "03_autoformalize_response.json").is_file()
            assert (case_dir / "04_detected_findings.json").is_file()
            assert (case_dir / "05_finding_assertions.smt2").is_file()
            assert (case_dir / "07_report.json").is_file()

            # Each of the 10 diagnoses should have .smt2 and .z3out
            from applications.radiology.verifier import DIAGNOSES
            for dx in DIAGNOSES:
                assert (case_dir / f"06_verify_{dx}.smt2").is_file()
                assert (case_dir / f"06_verify_{dx}.z3out").is_file()

    def test_finding_assertions_closed_world(self, pipeline_run):
        """SMT-LIB assertions should cover all canonical findings."""
        run_dir, summary = pipeline_run
        from applications.radiology.verifier import RADIOLOGY_FINDINGS
        # Check the first case
        case_dir = run_dir / summary["cases"][0]["dir"]
        smt2 = (case_dir / "05_finding_assertions.smt2").read_text()
        for finding in RADIOLOGY_FINDINGS:
            assert finding in smt2, f"Finding {finding} missing from assertions"

    def test_smt2_programs_contain_check_sat(self, pipeline_run):
        """Every verification .smt2 file must contain check-sat."""
        run_dir, summary = pipeline_run
        case_dir = run_dir / summary["cases"][0]["dir"]
        from applications.radiology.verifier import DIAGNOSES
        for dx in DIAGNOSES:
            smt2 = (case_dir / f"06_verify_{dx}.smt2").read_text()
            assert "(check-sat)" in smt2


# ---------------------------------------------------------------------------
# Summary — prints a readable report
# ---------------------------------------------------------------------------

class TestVLMSummary:
    """Print a human-readable summary of all 15 cases."""

    def test_print_summary(self, pipeline_run, autoformalized_cases, capsys):
        run_dir, summary = pipeline_run
        print("\n" + "=" * 72)
        print("  FULL-PIPELINE VLM VERIFICATION SUMMARY")
        print("  (VLM text → GPT-5.2 autoformalize → SMT-LIB → Z3)")
        print(f"  Log directory: {run_dir}")
        print("=" * 72)

        total_s, total_u, total_m = 0, 0, 0

        for case in VLM_CASES:
            report = autoformalized_cases[case.name]

            print(f"\n  Case: {case.name}")
            print(f"  VLM:  \"{case.vlm_text[:75]}...\"")
            print(f"  Extracted findings: {sorted(report.detected_findings)}")
            print(f"  Claimed diagnoses: {report.claimed_diagnoses}")

            for dx in report.supported:
                print(f"    + {DIAGNOSIS_LABELS[dx]:<22s} SUPPORTED")
            for dx in report.unsupported:
                print(f"    - {DIAGNOSIS_LABELS[dx]:<22s} NOT SUPPORTED")
            for dx in report.missed:
                print(f"    ! {DIAGNOSIS_LABELS[dx]:<22s} MISSED")

            total_s += len(report.supported)
            total_u += len(report.unsupported)
            total_m += len(report.missed)

        print("\n" + "-" * 72)
        print(f"  Total: {total_s} supported, {total_u} unsupported, "
              f"{total_m} missed")
        print(f"  All artifacts logged to: {run_dir}")
        print("=" * 72)
