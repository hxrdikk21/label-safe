"""
Unit Test Suite for Deterministic Clinical Screeners (Phase 3).
Tests DDI, DFI, DCI, and Allergy/Excipient screening engines across positive, negative, and edge cases.
"""

import pytest

from src.rxguard.core.contracts.medication import IngredientReference, MedicationConcept
from src.rxguard.core.contracts.product import DrugProduct
from src.rxguard.core.contracts.safety import FindingSeverity, FindingStatus
from src.rxguard.core.contracts.user_context import UserAllergyRecord, UserConditionRecord
from src.rxguard.safety.allergies import AllergyScreeningEngine
from src.rxguard.safety.contraindications import DCIScreeningEngine
from src.rxguard.safety.ddi import DDIScreeningEngine
from src.rxguard.safety.dfi import DFIScreeningEngine
from src.rxguard.safety.rules_db import get_safety_rules_repo


@pytest.fixture(scope="module")
def repo():
    return get_safety_rules_repo()


class TestDDIScreeningEngine:
    """Tests for pairwise Drug-Drug interaction screening."""

    @pytest.fixture
    def ddi_engine(self, repo):
        return DDIScreeningEngine(repository=repo)

    def test_empty_or_single_med_input(self, ddi_engine):
        assert ddi_engine.screen_pairs([]) == []
        med = MedicationConcept(rxcui="11289", canonical_name="Warfarin", term_type="IN")
        assert ddi_engine.screen_pairs([med]) == []

    def test_known_interacting_pair(self, ddi_engine):
        warfarin = MedicationConcept(rxcui="11289", canonical_name="Warfarin", term_type="IN")
        ibuprofen = MedicationConcept(rxcui="5640", canonical_name="Ibuprofen", term_type="IN")

        findings = ddi_engine.screen_pairs([warfarin, ibuprofen])
        assert len(findings) == 1
        f = findings[0]
        assert f.finding_type == "DRUG_DRUG_INTERACTION"
        assert f.status == FindingStatus.RISK_IDENTIFIED
        assert f.severity == FindingSeverity.CONTRAINDICATED
        assert set(f.subject_medications) == {"11289", "5640"}
        assert "Warfarin" in f.clinical_explanation
        assert "Ibuprofen" in f.clinical_explanation

    def test_three_medications_combinatorics(self, ddi_engine):
        # 3 medications: Warfarin (11289), Ibuprofen (5640), Lisinopril (29046)
        # Combinations: (Warfarin, Ibuprofen) -> HIT; (Warfarin, Lisinopril) -> MISS; (Ibuprofen, Lisinopril)
        # -> MISS
        meds = [
            MedicationConcept(rxcui="11289", canonical_name="Warfarin", term_type="IN"),
            MedicationConcept(rxcui="5640", canonical_name="Ibuprofen", term_type="IN"),
            MedicationConcept(rxcui="29046", canonical_name="Lisinopril", term_type="IN"),
        ]
        findings = ddi_engine.screen_pairs(meds)
        assert len(findings) == 1
        assert set(findings[0].subject_medications) == {"11289", "5640"}

    def test_benign_pair(self, ddi_engine):
        lisinopril = MedicationConcept(rxcui="29046", canonical_name="Lisinopril", term_type="IN")
        metformin = MedicationConcept(rxcui="6809", canonical_name="Metformin", term_type="IN")
        assert ddi_engine.screen_pairs([lisinopril, metformin]) == []

    def test_duplicate_rxcui_deduplication(self, ddi_engine):
        meds = [
            MedicationConcept(rxcui="11289", canonical_name="Warfarin", term_type="IN"),
            MedicationConcept(rxcui="11289", canonical_name="Warfarin 5mg", term_type="SCD"),
            MedicationConcept(rxcui="5640", canonical_name="Ibuprofen", term_type="IN"),
        ]
        findings = ddi_engine.screen_pairs(meds)
        # Should deduplicate 11289 and evaluate exactly 1 distinct pair
        assert len(findings) == 1

    def test_screen_raw_rxcuis(self, ddi_engine):
        findings = ddi_engine.screen_rxcuis(["136443", "4917"])  # Sildenafil + Nitroglycerin
        assert len(findings) == 1
        assert findings[0].severity == FindingSeverity.CONTRAINDICATED


class TestDFIScreeningEngine:
    """Tests for Drug-Food interaction screening."""

    @pytest.fixture
    def dfi_engine(self, repo):
        return DFIScreeningEngine(repository=repo)

    def test_empty_inputs(self, dfi_engine):
        assert dfi_engine.screen_food_interactions([], ["grapefruit"]) == []
        assert dfi_engine.screen_food_interactions(["83367"], []) == []

    def test_atorvastatin_grapefruit(self, dfi_engine):
        atorva = MedicationConcept(rxcui="83367", canonical_name="Atorvastatin", term_type="IN")
        findings = dfi_engine.screen_food_interactions([atorva], ["Fresh Grapefruit Juice"])
        assert len(findings) == 1
        f = findings[0]
        assert f.finding_type == "DRUG_FOOD_INTERACTION"
        assert f.severity == FindingSeverity.MAJOR
        assert "grapefruit" in f.actionable_warning.lower()

    def test_ciprofloxacin_dairy_timing(self, dfi_engine):
        findings = dfi_engine.screen_food_interactions(["2551"], ["Whole Milk / Dairy"])
        assert len(findings) == 1
        f = findings[0]
        assert f.severity == FindingSeverity.MODERATE
        assert "timing" in f.actionable_warning.lower()

    def test_metronidazole_alcohol(self, dfi_engine):
        findings = dfi_engine.screen_food_interactions(["6922"], ["Alcohol"])
        assert len(findings) == 1
        assert "disulfiram" in findings[0].clinical_explanation.lower()

    def test_benign_food_interaction(self, dfi_engine):
        findings = dfi_engine.screen_food_interactions(["83367"], ["Apples", "Bananas"])
        assert len(findings) == 0


class TestDCIScreeningEngine:
    """Tests for Drug-Condition contraindication screening."""

    @pytest.fixture
    def dci_engine(self, repo):
        return DCIScreeningEngine(repository=repo)

    def test_empty_inputs(self, dci_engine):
        assert dci_engine.screen_contraindications([], ["J45"]) == []
        assert dci_engine.screen_contraindications(["8787"], []) == []

    def test_propranolol_in_asthma(self, dci_engine):
        propranolol = MedicationConcept(rxcui="8787", canonical_name="Propranolol", term_type="IN")
        findings = dci_engine.screen_contraindications([propranolol], ["J45"])
        assert len(findings) == 1
        f = findings[0]
        assert f.finding_type == "CONTRAINDICATION"
        assert f.severity == FindingSeverity.CONTRAINDICATED
        assert "ABSOLUTE CONTRAINDICATION" in f.clinical_explanation
        assert "Asthma" in f.clinical_explanation

    def test_metformin_with_user_condition_record(self, dci_engine):
        cond = UserConditionRecord(
            condition_name="Stage 4 Chronic Kidney Disease",
            icd10_code="N18.4",
            diagnosed_date="2023-05-10",
        )
        findings = dci_engine.screen_contraindications(["6809"], [cond])
        assert len(findings) == 1
        f = findings[0]
        assert f.severity == FindingSeverity.CONTRAINDICATED
        assert "lactic acidosis" in f.clinical_explanation.lower()

    def test_safe_condition(self, dci_engine):
        propranolol = MedicationConcept(rxcui="8787", canonical_name="Propranolol", term_type="IN")
        # Propranolol in Osteoarthritis (M15) has no contraindication
        assert dci_engine.screen_contraindications([propranolol], ["M15"]) == []


class TestAllergyScreeningEngine:
    """Tests for Allergy and Excipient cross-reactivity screening."""

    @pytest.fixture
    def allergy_engine(self, repo):
        return AllergyScreeningEngine(repository=repo)

    def test_empty_inputs(self, allergy_engine):
        assert allergy_engine.screen_allergies([], ["Penicillin"]) == []
        assert allergy_engine.screen_allergies(["723"], []) == []

    def test_penicillin_allergy_with_amoxicillin_concept(self, allergy_engine):
        amox_ing = IngredientReference(unii="804826J2HU", name="Amoxicillin", is_active=True)
        amox = MedicationConcept(
            rxcui="723",
            canonical_name="Amoxicillin",
            term_type="IN",
            ingredients=[amox_ing],
        )
        findings = allergy_engine.screen_allergies([amox], ["Penicillin Allergy"])
        assert len(findings) == 1
        f = findings[0]
        assert f.finding_type == "ALLERGY_EXCIPIENT"
        assert f.severity == FindingSeverity.CONTRAINDICATED
        assert "BETA-LACTAM" in f.clinical_explanation

    def test_user_allergy_record_cephalexin(self, allergy_engine):
        user_allergy = UserAllergyRecord(
            substance_name="Penicillins",
            allergy_class="Beta-Lactam",
            severity="SEVERE_ANAPHYLAXIS",
            verification_source="CLINICIAN_VERIFIED",
        )
        # Cephalexin RxCUI is 2231
        findings = allergy_engine.screen_allergies(["2231"], [user_allergy])
        assert len(findings) == 1
        assert findings[0].severity == FindingSeverity.CONTRAINDICATED

    def test_tartrazine_excipient_in_drug_product(self, allergy_engine):
        prod = DrugProduct(
            ndc="0001-0002-03",
            rxcui="99999",
            brand_name="Yellow Tablet",
            generic_name="Sample Generic",
            dosage_form="Tablet",
            route="Oral",
            strength="10mg",
            spl_setid="SPL-TEST",
            active_ingredient_uniis=["SOME_ACTIVE_UNII"],
            inactive_excipient_uniis=["EWQ57Q8I5X"],  # Tartrazine UNII
        )
        findings = allergy_engine.screen_allergies([prod], ["Tartrazine dye"])
        assert len(findings) == 1
        assert "Tartrazine" in findings[0].clinical_explanation

    def test_non_allergic_medication(self, allergy_engine):
        # Atorvastatin (83367) in Penicillin-allergic patient
        findings = allergy_engine.screen_allergies(["83367"], ["Penicillin"])
        assert len(findings) == 0
