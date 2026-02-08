"""Radiology diagnostic verification via staged SMT pipeline.

Encodes standard radiological decision procedures as SMT-LIB biconditionals,
then verifies whether a VLM's claimed diagnoses are logically entailed by
the detected findings.

Usage:
    verifier = RadiologyVerifier(z3_path="z3")
    result = verifier.verify_diagnosis(
        detected_findings={"focal_opacity", "air_bronchogram"},
        diagnosis="pneumonia",
    )
    print(result.entailed)  # True — findings entail pneumonia
"""

from __future__ import annotations

import logging
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from z3adapter.backends.smt2.backend import StagedSMT2Backend

logger = logging.getLogger(__name__)


def find_z3() -> str:
    """Locate the Z3 executable, checking the current venv first."""
    # 1. Global PATH
    found = shutil.which("z3")
    if found:
        return found
    # 2. Same venv/bin as the running Python
    venv_z3 = Path(sys.executable).parent / "z3"
    if venv_z3.is_file():
        return str(venv_z3)
    return "z3"  # fallback — will raise at StagedSMT2Backend init

# ---------------------------------------------------------------------------
# Canonical finding names (all Bool constants)
# ---------------------------------------------------------------------------

RADIOLOGY_FINDINGS: list[str] = [
    # Pneumonia
    "focal_opacity",
    "ground_glass_opacity",
    "dense_opacity",
    "air_bronchogram",
    # Pneumothorax
    "visible_pleural_line",
    "absent_lung_markings",
    "deep_sulcus_sign",
    # Pulmonary Edema
    "bilateral_infiltrates",
    "bilateral_opacities",
    "cephalization",
    "kerley_b_lines",
    "peribronchial_cuffing",
    # Consolidation (reuses dense_opacity, air_bronchogram)
    "silhouette_sign_loss",
    # Atelectasis
    "volume_loss",
    "fissure_displacement",
    "linear_opacity",
    "increased_opacity",
    # Pleural Effusion
    "costophrenic_blunting",
    "meniscus_sign",
    "layering_fluid",
    # Fracture
    "cortical_break",
    # Cardiomegaly
    "enlarged_cardiac_silhouette",
    "increased_cardiothoracic_ratio",
    # Emphysema
    "hyperinflation",
    "flattened_diaphragm",
    "bullae",
    # Fibrosis
    "reticular_opacities",
    "honeycombing",
    "traction_bronchiectasis",
    # volume_loss already listed under Atelectasis
]

# ---------------------------------------------------------------------------
# Diagnostic criteria  —  DSL expressions (Python-like, parsed by emitter)
# ---------------------------------------------------------------------------

DIAGNOSES: list[str] = [
    "pneumonia_dx",
    "pneumothorax_dx",
    "pulmonary_edema_dx",
    "consolidation_dx",
    "atelectasis_dx",
    "pleural_effusion_dx",
    "fracture_dx",
    "cardiomegaly_dx",
    "emphysema_dx",
    "fibrosis_dx",
]

# Maps diagnosis constant name -> DSL expression for the required findings.
# These are biconditional rules:  diagnosis ⟺ (criteria met)
DIAGNOSTIC_RULES: dict[str, str] = {
    "pneumonia_dx": (
        "Or(focal_opacity, ground_glass_opacity, dense_opacity) "
        "and air_bronchogram"
    ),
    "pneumothorax_dx": (
        "visible_pleural_line "
        "or (absent_lung_markings and deep_sulcus_sign)"
    ),
    "pulmonary_edema_dx": (
        "(bilateral_infiltrates or bilateral_opacities) "
        "and (cephalization or kerley_b_lines or peribronchial_cuffing)"
    ),
    "consolidation_dx": (
        "dense_opacity "
        "and (air_bronchogram or silhouette_sign_loss)"
    ),
    "atelectasis_dx": (
        "(volume_loss or fissure_displacement) "
        "and (linear_opacity or increased_opacity)"
    ),
    "pleural_effusion_dx": (
        "costophrenic_blunting or meniscus_sign or layering_fluid"
    ),
    "fracture_dx": "cortical_break",
    "cardiomegaly_dx": (
        "enlarged_cardiac_silhouette or increased_cardiothoracic_ratio"
    ),
    "emphysema_dx": (
        "hyperinflation and (flattened_diaphragm or bullae)"
    ),
    "fibrosis_dx": (
        "(reticular_opacities or honeycombing) "
        "and (traction_bronchiectasis or volume_loss)"
    ),
}

# Human-readable label for each diagnosis constant
DIAGNOSIS_LABELS: dict[str, str] = {
    "pneumonia_dx": "Pneumonia",
    "pneumothorax_dx": "Pneumothorax",
    "pulmonary_edema_dx": "Pulmonary Edema",
    "consolidation_dx": "Consolidation",
    "atelectasis_dx": "Atelectasis",
    "pleural_effusion_dx": "Pleural Effusion",
    "fracture_dx": "Fracture",
    "cardiomegaly_dx": "Cardiomegaly",
    "emphysema_dx": "Emphysema",
    "fibrosis_dx": "Fibrosis",
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class DiagnosisResult:
    """Result of verifying a single diagnosis."""

    diagnosis: str
    label: str
    entailed: bool
    z3_status: str  # "sat" or "unsat"
    smt2_program: str = ""  # The full SMT-LIB program sent to Z3
    raw_output: str = ""  # Z3 stdout/stderr


@dataclass
class VerificationReport:
    """Full verification report for a case."""

    detected_findings: set[str]
    claimed_diagnoses: list[str]
    results: dict[str, DiagnosisResult] = field(default_factory=dict)
    supported: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# RadiologyVerifier
# ---------------------------------------------------------------------------

class RadiologyVerifier:
    """Verifies radiological diagnoses against detected findings using Z3.

    The verifier builds a static SMT-LIB foundation once (diagnostic rules),
    then for each case constructs per-case assertions and queries.

    Args:
        z3_path: Path to the Z3 executable.
    """

    def __init__(self, z3_path: str | None = None) -> None:
        self.backend = StagedSMT2Backend(z3_path=z3_path or find_z3())
        self._foundation_config = self._build_foundation_config()
        self._foundation_smt2 = self.backend.build_foundation(
            self._foundation_config, through_stage="rules"
        )

    # -- Foundation --------------------------------------------------------

    @staticmethod
    def _build_foundation_config() -> dict[str, Any]:
        """Return the static DSL config for all findings, diagnoses, and rules."""
        # All Bool constants: findings + diagnosis flags
        constants: dict[str, Any] = {
            "findings": {
                "sort": "Bool",
                "members": RADIOLOGY_FINDINGS,
            },
            "diagnoses": {
                "sort": "Bool",
                "members": DIAGNOSES,
            },
        }

        # Biconditional rules:  diagnosis == criteria
        rules: list[dict[str, Any]] = []
        for dx, criteria_expr in DIAGNOSTIC_RULES.items():
            rules.append({
                "constraint": f"{dx} == ({criteria_expr})",
            })

        return {
            "constants": constants,
            "rules": rules,
        }

    # -- Per-case verification ---------------------------------------------

    def _build_case_config(self, detected_findings: set[str]) -> dict[str, Any]:
        """Extend the static foundation config with closed-world finding assertions.

        Each canonical finding is asserted true if detected, false otherwise,
        via the library's KnowledgeBaseStage.

        Args:
            detected_findings: Set of finding names that were detected.

        Returns:
            DSL config dict with constants, rules, and knowledge_base.
        """
        kb = [
            {"assertion": f, "value": f in detected_findings}
            for f in RADIOLOGY_FINDINGS
        ]
        return {**self._foundation_config, "knowledge_base": kb}

    def verify_diagnosis(
        self,
        detected_findings: set[str],
        diagnosis: str,
        *,
        _case_foundation: str | None = None,
    ) -> DiagnosisResult:
        """Check whether a single diagnosis is entailed by the findings.

        Args:
            detected_findings: Set of detected finding names.
            diagnosis: Diagnosis constant (e.g. "pneumonia_dx").
            _case_foundation: Pre-built foundation (internal, for verify_all).

        Returns:
            DiagnosisResult with entailment status.

        Raises:
            ValueError: If diagnosis is not recognized.
        """
        if diagnosis not in DIAGNOSTIC_RULES:
            raise ValueError(
                f"Unknown diagnosis: '{diagnosis}'. "
                f"Valid diagnoses: {list(DIAGNOSTIC_RULES.keys())}"
            )

        if _case_foundation is None:
            case_config = self._build_case_config(detected_findings)
            _case_foundation = self.backend.build_foundation(
                case_config, through_stage="rules"
            )

        smt2_program = self.backend.add_query(
            {"name": f"entailment_{diagnosis}", "constraint": f"Not({diagnosis})"},
            foundation=_case_foundation,
        )
        result = self.backend.execute_from_string(smt2_program)

        # UNSAT means the negated diagnosis is inconsistent with the
        # findings + rules  →  the diagnosis IS entailed.
        entailed = result.answer is False  # answer=False means UNSAT
        z3_status = "unsat" if result.answer is False else "sat"

        return DiagnosisResult(
            diagnosis=diagnosis,
            label=DIAGNOSIS_LABELS.get(diagnosis, diagnosis),
            entailed=entailed,
            z3_status=z3_status,
            smt2_program=smt2_program,
            raw_output=result.output,
        )

    def verify_all(
        self,
        detected_findings: set[str],
        claimed_diagnoses: list[str] | None = None,
    ) -> VerificationReport:
        """Verify all claimed diagnoses and find any missed ones.

        Builds the case foundation once, then runs add_query() per diagnosis.

        Args:
            detected_findings: Set of detected finding names.
            claimed_diagnoses: Diagnoses claimed by the VLM. If None,
                checks all diagnoses (discovery mode).

        Returns:
            VerificationReport with supported, unsupported, and missed lists.
        """
        if claimed_diagnoses is None:
            claimed_diagnoses = []

        claimed_set = set(claimed_diagnoses)

        report = VerificationReport(
            detected_findings=detected_findings,
            claimed_diagnoses=claimed_diagnoses,
        )

        # Build the case foundation once (constants + rules + findings KB)
        case_config = self._build_case_config(detected_findings)
        case_foundation = self.backend.build_foundation(
            case_config, through_stage="rules"
        )

        # Check every diagnosis using the shared foundation
        for dx in DIAGNOSES:
            result = self.verify_diagnosis(
                detected_findings, dx, _case_foundation=case_foundation
            )
            report.results[dx] = result

            if dx in claimed_set:
                if result.entailed:
                    report.supported.append(dx)
                else:
                    report.unsupported.append(dx)
            else:
                if result.entailed:
                    report.missed.append(dx)

        return report

