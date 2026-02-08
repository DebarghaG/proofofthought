"""Unit tests for the RadiologyVerifier.

These tests validate the SMT encoding and entailment logic without
requiring a live LLM — they use hardcoded finding sets.

Run:
    python -m pytest applications/radiology/test_verifier.py -v
"""

from __future__ import annotations

import pytest

from applications.radiology.verifier import (
    DIAGNOSES,
    DIAGNOSTIC_RULES,
    DIAGNOSIS_LABELS,
    RADIOLOGY_FINDINGS,
    RadiologyVerifier,
    find_z3,
)


# ---------------------------------------------------------------------------
# Fixture: shared verifier instance (foundation built once)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def verifier():
    """Create a RadiologyVerifier (auto-discovers Z3 in venv)."""
    try:
        return RadiologyVerifier()
    except FileNotFoundError:
        pytest.skip("Z3 not installed — skipping radiology verifier tests")


# ---------------------------------------------------------------------------
# Foundation / config tests (no Z3 needed)
# ---------------------------------------------------------------------------

class TestFoundationConfig:
    """Tests for the static foundation configuration."""

    def test_all_findings_listed(self):
        assert len(RADIOLOGY_FINDINGS) >= 28

    def test_all_diagnoses_have_rules(self):
        for dx in DIAGNOSES:
            assert dx in DIAGNOSTIC_RULES, f"Missing rule for {dx}"

    def test_all_diagnoses_have_labels(self):
        for dx in DIAGNOSES:
            assert dx in DIAGNOSIS_LABELS, f"Missing label for {dx}"

    def test_foundation_config_structure(self):
        config = RadiologyVerifier._build_foundation_config()
        assert "constants" in config
        assert "rules" in config
        assert "findings" in config["constants"]
        assert "diagnoses" in config["constants"]
        assert len(config["rules"]) == len(DIAGNOSTIC_RULES)

    def test_no_duplicate_findings(self):
        assert len(RADIOLOGY_FINDINGS) == len(set(RADIOLOGY_FINDINGS))

    def test_no_duplicate_diagnoses(self):
        assert len(DIAGNOSES) == len(set(DIAGNOSES))


# ---------------------------------------------------------------------------
# SMT generation tests (no Z3 execution needed)
# ---------------------------------------------------------------------------

class TestCaseConfig:
    """Tests for the per-case DSL configuration."""

    def test_foundation_generates_smt2(self, verifier):
        assert verifier._foundation_smt2
        assert "(declare-const focal_opacity Bool)" in verifier._foundation_smt2
        assert "(declare-const pneumonia_dx Bool)" in verifier._foundation_smt2

    def test_case_config_has_knowledge_base(self, verifier):
        config = verifier._build_case_config({"focal_opacity", "air_bronchogram"})
        assert "knowledge_base" in config
        assert "constants" in config
        assert "rules" in config
        kb = config["knowledge_base"]
        assert len(kb) == len(RADIOLOGY_FINDINGS)

    def test_case_config_closed_world(self, verifier):
        """All findings present in KB, detected ones True, others False."""
        detected = {"cortical_break"}
        config = verifier._build_case_config(detected)
        kb = {entry["assertion"]: entry["value"] for entry in config["knowledge_base"]}
        for f in RADIOLOGY_FINDINGS:
            assert f in kb, f"Missing finding {f} from knowledge_base"
            if f == "cortical_break":
                assert kb[f] is True
            else:
                assert kb[f] is False

    def test_case_config_detected_values(self, verifier):
        """Detected findings should have value=True in the KB."""
        detected = {"focal_opacity", "air_bronchogram"}
        config = verifier._build_case_config(detected)
        kb = {entry["assertion"]: entry["value"] for entry in config["knowledge_base"]}
        assert kb["focal_opacity"] is True
        assert kb["air_bronchogram"] is True
        assert kb["ground_glass_opacity"] is False


# ---------------------------------------------------------------------------
# Entailment tests (require Z3)
# ---------------------------------------------------------------------------

class TestEntailment:
    """Tests that require Z3 to execute SMT-LIB programs."""

    # -- Pneumonia ---------------------------------------------------------

    def test_pneumonia_entailed(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"focal_opacity", "air_bronchogram"},
            diagnosis="pneumonia_dx",
        )
        assert result.entailed is True
        assert result.z3_status == "unsat"

    def test_pneumonia_ground_glass(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"ground_glass_opacity", "air_bronchogram"},
            diagnosis="pneumonia_dx",
        )
        assert result.entailed is True

    def test_pneumonia_not_entailed_without_bronchogram(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"focal_opacity"},
            diagnosis="pneumonia_dx",
        )
        assert result.entailed is False
        assert result.z3_status == "sat"

    # -- Pneumothorax ------------------------------------------------------

    def test_pneumothorax_pleural_line(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"visible_pleural_line"},
            diagnosis="pneumothorax_dx",
        )
        assert result.entailed is True

    def test_pneumothorax_absent_markings_deep_sulcus(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"absent_lung_markings", "deep_sulcus_sign"},
            diagnosis="pneumothorax_dx",
        )
        assert result.entailed is True

    def test_pneumothorax_not_entailed(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"absent_lung_markings"},
            diagnosis="pneumothorax_dx",
        )
        assert result.entailed is False

    # -- Pleural Effusion --------------------------------------------------

    def test_pleural_effusion_costophrenic(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"costophrenic_blunting"},
            diagnosis="pleural_effusion_dx",
        )
        assert result.entailed is True

    def test_pleural_effusion_meniscus(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"meniscus_sign"},
            diagnosis="pleural_effusion_dx",
        )
        assert result.entailed is True

    # -- Fracture ----------------------------------------------------------

    def test_fracture_entailed(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"cortical_break"},
            diagnosis="fracture_dx",
        )
        assert result.entailed is True

    def test_fracture_not_entailed(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings=set(),
            diagnosis="fracture_dx",
        )
        assert result.entailed is False

    # -- Cardiomegaly ------------------------------------------------------

    def test_cardiomegaly_enlarged(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"enlarged_cardiac_silhouette"},
            diagnosis="cardiomegaly_dx",
        )
        assert result.entailed is True

    def test_cardiomegaly_ratio(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"increased_cardiothoracic_ratio"},
            diagnosis="cardiomegaly_dx",
        )
        assert result.entailed is True

    # -- Consolidation -----------------------------------------------------

    def test_consolidation_entailed(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"dense_opacity", "air_bronchogram"},
            diagnosis="consolidation_dx",
        )
        assert result.entailed is True

    def test_consolidation_silhouette(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"dense_opacity", "silhouette_sign_loss"},
            diagnosis="consolidation_dx",
        )
        assert result.entailed is True

    # -- Emphysema ---------------------------------------------------------

    def test_emphysema_entailed(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"hyperinflation", "flattened_diaphragm"},
            diagnosis="emphysema_dx",
        )
        assert result.entailed is True

    def test_emphysema_not_entailed_partial(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"hyperinflation"},
            diagnosis="emphysema_dx",
        )
        assert result.entailed is False

    # -- Fibrosis ----------------------------------------------------------

    def test_fibrosis_entailed(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"reticular_opacities", "traction_bronchiectasis"},
            diagnosis="fibrosis_dx",
        )
        assert result.entailed is True

    def test_fibrosis_honeycombing_volume_loss(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"honeycombing", "volume_loss"},
            diagnosis="fibrosis_dx",
        )
        assert result.entailed is True

    # -- Atelectasis -------------------------------------------------------

    def test_atelectasis_entailed(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"volume_loss", "linear_opacity"},
            diagnosis="atelectasis_dx",
        )
        assert result.entailed is True

    # -- Pulmonary Edema ---------------------------------------------------

    def test_pulmonary_edema_entailed(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"bilateral_infiltrates", "cephalization"},
            diagnosis="pulmonary_edema_dx",
        )
        assert result.entailed is True

    def test_pulmonary_edema_not_entailed_partial(self, verifier):
        result = verifier.verify_diagnosis(
            detected_findings={"bilateral_infiltrates"},
            diagnosis="pulmonary_edema_dx",
        )
        assert result.entailed is False

    # -- No findings → no diagnoses ----------------------------------------

    def test_no_findings_no_diagnoses(self, verifier):
        """With no findings detected, no diagnosis should be entailed."""
        for dx in DIAGNOSES:
            result = verifier.verify_diagnosis(
                detected_findings=set(),
                diagnosis=dx,
            )
            assert result.entailed is False, (
                f"{dx} should NOT be entailed with no findings"
            )


# ---------------------------------------------------------------------------
# verify_all tests
# ---------------------------------------------------------------------------

class TestVerifyAll:
    """Tests for the verify_all method."""

    def test_verify_all_basic(self, verifier):
        report = verifier.verify_all(
            detected_findings={"focal_opacity", "air_bronchogram"},
            claimed_diagnoses=["pneumonia_dx"],
        )
        assert "pneumonia_dx" in report.supported
        assert len(report.unsupported) == 0

    def test_verify_all_unsupported(self, verifier):
        report = verifier.verify_all(
            detected_findings={"focal_opacity"},
            claimed_diagnoses=["pneumonia_dx"],
        )
        assert "pneumonia_dx" in report.unsupported
        assert len(report.supported) == 0

    def test_verify_all_missed(self, verifier):
        report = verifier.verify_all(
            detected_findings={"focal_opacity", "air_bronchogram", "cortical_break"},
            claimed_diagnoses=["pneumonia_dx"],
        )
        assert "pneumonia_dx" in report.supported
        assert "fracture_dx" in report.missed

    def test_verify_all_discovery_mode(self, verifier):
        """When no diagnoses are claimed, all entailed ones appear as missed."""
        report = verifier.verify_all(
            detected_findings={"cortical_break"},
            claimed_diagnoses=[],
        )
        assert "fracture_dx" in report.missed
        assert len(report.supported) == 0
        assert len(report.unsupported) == 0

    def test_verify_all_multiple_findings(self, verifier):
        """Multiple diagnoses can be supported simultaneously."""
        report = verifier.verify_all(
            detected_findings={
                "dense_opacity",
                "air_bronchogram",
                "enlarged_cardiac_silhouette",
            },
            claimed_diagnoses=["pneumonia_dx", "consolidation_dx", "cardiomegaly_dx"],
        )
        assert "pneumonia_dx" in report.supported
        assert "consolidation_dx" in report.supported
        assert "cardiomegaly_dx" in report.supported


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Tests for error handling."""

    def test_unknown_diagnosis_raises(self, verifier):
        with pytest.raises(ValueError, match="Unknown diagnosis"):
            verifier.verify_diagnosis(set(), "nonexistent_dx")
