"""
Unit Test Suite for Master Safety Engine (Phase 4).
Tests multi-workflow synthesis, missing data handling, severity ranking, and fail-safe statuses.
"""

import pytest

from src.labelsafe.core.contracts.medication import IngredientReference, MedicationConcept
from src.labelsafe.core.contracts.safety import FindingSeverity, FindingStatus
from src.labelsafe.core.contracts.user_context import UserAllergyRecord, UserConditionRecord
from src.labelsafe.safety.engine import ClinicalSafetyReport, SafetyEngine
from src.labelsafe.safety.rules_db import get_safety_rules_repo


@pytest.fixture(scope="module")
def safety_engine():
    repo = get_safety_rules_repo()
    return SafetyEngine(repository=repo)


class TestSafetyEngineMaster:
    """Tests for the Master SafetyEngine orchestrator."""

    def test_multi_hazard_patient_profile(self, safety_engine):
        # Patient on Warfarin + Ibuprofen + Propranolol with Asthma and Penicillin Allergy
        amox_ing = IngredientReference(unii="804826J2HU", name="Amoxicillin", is_active=True)
        meds = [
            MedicationConcept(rxcui="11289", canonical_name="Warfarin", term_type="IN"),
            MedicationConcept(rxcui="5640", canonical_name="Ibuprofen", term_type="IN"),
            MedicationConcept(rxcui="8787", canonical_name="Propranolol", term_type="IN"),
            MedicationConcept(
                rxcui="723", canonical_name="Amoxicillin", term_type="IN", ingredients=[amox_ing]
            ),
        ]
        conditions = [UserConditionRecord(condition_name="Bronchial Asthma", icd10_code="J45")]
        allergies = [UserAllergyRecord(substance_name="Penicillin Allergy", severity="SEVERE_ANAPHYLAXIS")]
        food_items = ["Grapefruit Juice"]

        report = safety_engine.evaluate_clinical_profile(
            medications=meds,
            conditions=conditions,
            allergies=allergies,
            food_items=food_items,
        )

        assert isinstance(report, ClinicalSafetyReport)
        assert report.evaluated_medication_count == 4
        assert (
            len(report.findings) >= 3
        )  # DDI (Warfarin+Ibuprofen), DCI (Propranolol+Asthma), Allergy (Amoxicillin+Penicillin)

        types_found = {f.finding_type for f in report.findings}
        assert "DRUG_DRUG_INTERACTION" in types_found
        assert "CONTRAINDICATION" in types_found
        assert "ALLERGY_EXCIPIENT" in types_found

        assert report.highest_severity == FindingSeverity.CONTRAINDICATED
        assert report.overall_status == FindingStatus.RISK_IDENTIFIED
        assert len(report.disclaimer) > 20

    def test_missing_data_warnings_when_context_omitted(self, safety_engine):
        # Only medications supplied; conditions and allergies are None
        meds = [
            MedicationConcept(rxcui="29046", canonical_name="Lisinopril", term_type="IN"),
            MedicationConcept(rxcui="6809", canonical_name="Metformin", term_type="IN"),
        ]
        report = safety_engine.evaluate_clinical_profile(
            medications=meds,
            conditions=None,
            allergies=None,
        )

        # Benign pair has 0 DDI findings, but conditions and allergies were omitted
        assert len(report.findings) == 0
        assert len(report.missing_data_warnings) == 2
        assert any("condition" in w.lower() for w in report.missing_data_warnings)
        assert any("allergy" in w.lower() for w in report.missing_data_warnings)
        assert report.overall_status == FindingStatus.INSUFFICIENT_EVIDENCE

    def test_ambiguous_medication_status(self, safety_engine):
        med = MedicationConcept(
            rxcui="6918",
            canonical_name="Metoprolol",
            term_type="IN",
            is_ambiguous=True,
            ambiguity_candidates=["866416", "866428"],
        )
        report = safety_engine.evaluate_clinical_profile(
            medications=[med],
            conditions=[],
            allergies=[],
        )
        assert report.overall_status == FindingStatus.AMBIGUOUS_MEDICATION_IDENTITY
        assert any("ambiguous" in w.lower() for w in report.missing_data_warnings)

    def test_fully_cleared_patient_no_issue(self, safety_engine):
        # Lisinopril + Metformin with fully supplied benign history
        meds = [
            MedicationConcept(rxcui="29046", canonical_name="Lisinopril", term_type="IN"),
            MedicationConcept(rxcui="6809", canonical_name="Metformin", term_type="IN"),
        ]
        conditions = [UserConditionRecord(condition_name="Hypertension", icd10_code="I10")]
        allergies = [UserAllergyRecord(substance_name="Sulfa", severity="MILD")]
        report = safety_engine.evaluate_clinical_profile(
            medications=meds,
            conditions=conditions,
            allergies=allergies,
            food_items=["Water"],
        )

        assert len(report.findings) == 0
        assert len(report.missing_data_warnings) == 0
        assert report.overall_status == FindingStatus.NO_ISSUE_FOUND_IN_CHECKED_SOURCES
        assert report.highest_severity == FindingSeverity.UNKNOWN_SEVERITY
