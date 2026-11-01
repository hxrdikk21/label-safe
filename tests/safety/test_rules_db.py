"""
Unit Test Suite for Deterministic Safety Rule Repository & Models (Phase 2).
Tests rule validation, symmetric DDI lookup, DFI substring matching, DCI prefix matching, and allergy
matching.
"""

import pytest
from pydantic import ValidationError

from src.rxguard.core.contracts.safety import FindingSeverity
from src.rxguard.safety.models import (
    AllergyRule,
    DCIRule,
    DDIRule,
    DFIRule,
    RuleStatus,
)
from src.rxguard.safety.rules_db import SafetyRulesRepository, get_safety_rules_repo


class TestSafetyRuleModels:
    """Tests for Pydantic validation of safety rule schemas."""

    def test_valid_ddi_rule(self):
        rule = DDIRule(
            rule_id="RULE-DDI-TEST-01",
            subject_rxcui="11289",
            interacting_rxcui="5640",
            subject_name="Warfarin",
            interacting_name="Ibuprofen",
            severity=FindingSeverity.CONTRAINDICATED,
            mechanism_summary="COX-1 inhibition plus vitamin K antagonism.",
            clinical_consequence="Severe gastrointestinal hemorrhage.",
            actionable_warning="Avoid combination.",
            source_document_ids=["SPL-001"],
            status=RuleStatus.ACTIVE,
        )
        assert rule.rule_id == "RULE-DDI-TEST-01"
        assert rule.severity == FindingSeverity.CONTRAINDICATED
        assert rule.status == RuleStatus.ACTIVE

    def test_reject_extra_fields_on_rules(self):
        with pytest.raises(ValidationError):
            DDIRule(
                rule_id="RULE-TEST",
                subject_rxcui="11289",
                interacting_rxcui="5640",
                severity=FindingSeverity.MAJOR,
                mechanism_summary="mechanism",
                clinical_consequence="consequence",
                actionable_warning="warning",
                unsupported_extra_field="invalid",
            )

    def test_valid_dfi_rule(self):
        rule = DFIRule(
            rule_id="RULE-DFI-TEST-01",
            subject_rxcui="83367",
            subject_name="Atorvastatin",
            food_identifier="grapefruit",
            severity=FindingSeverity.MAJOR,
            mechanism_summary="CYP3A4 intestinal inhibition.",
            clinical_consequence="Myopathy and rhabdomyolysis.",
            actionable_warning="Avoid grapefruit juice.",
            timing_qualifier="Avoid completely.",
        )
        assert rule.food_identifier == "grapefruit"

    def test_valid_dci_rule(self):
        rule = DCIRule(
            rule_id="RULE-DCI-TEST-01",
            subject_rxcui="8787",
            subject_name="Propranolol",
            condition_code="J45",
            condition_display="Asthma",
            is_absolute_contraindication=True,
            severity=FindingSeverity.CONTRAINDICATED,
            mechanism_summary="Beta-2 blockade.",
            clinical_consequence="Severe bronchospasm.",
            actionable_warning="Do not administer.",
        )
        assert rule.is_absolute_contraindication is True
        assert rule.condition_code == "J45"

    def test_valid_allergy_rule(self):
        rule = AllergyRule(
            rule_id="RULE-ALLERG-TEST-01",
            allergen_group_id="ALLERG-PENICILLIN",
            allergen_name="Penicillins",
            cross_reactive_uniis=["804826J2HU"],
            cross_reactive_rxcuis=["723"],
            risk_level="HIGH",
            clinical_manifestation="Anaphylaxis",
            actionable_warning="Avoid beta-lactams.",
        )
        assert "723" in rule.cross_reactive_rxcuis


class TestSafetyRulesRepository:
    """Tests for repository indexing, querying, and lookup semantics."""

    @pytest.fixture
    def empty_repo(self):
        return SafetyRulesRepository()

    def test_symmetric_ddi_lookup(self, empty_repo):
        rule = DDIRule(
            rule_id="RULE-DDI-01",
            subject_rxcui="11289",
            interacting_rxcui="5640",
            subject_name="Warfarin",
            interacting_name="Ibuprofen",
            severity=FindingSeverity.CONTRAINDICATED,
            mechanism_summary="mechanism",
            clinical_consequence="bleeding",
            actionable_warning="warning",
        )
        empty_repo.add_ddi_rule(rule)

        # Lookup as (11289, 5640)
        found1 = empty_repo.find_ddi("11289", "5640")
        assert found1 is not None
        assert found1.rule_id == "RULE-DDI-01"

        # Symmetrical lookup as (5640, 11289)
        found2 = empty_repo.find_ddi("5640", "11289")
        assert found2 is not None
        assert found2.rule_id == "RULE-DDI-01"

        # Non-existent pair
        assert empty_repo.find_ddi("11289", "9999") is None

    def test_dfi_substring_matching(self, empty_repo):
        rule = DFIRule(
            rule_id="RULE-DFI-01",
            subject_rxcui="83367",
            food_identifier="grapefruit",
            severity=FindingSeverity.MAJOR,
            mechanism_summary="mechanism",
            clinical_consequence="myopathy",
            actionable_warning="warning",
        )
        empty_repo.add_dfi_rule(rule)

        # Exact match
        assert empty_repo.find_dfi("83367", "grapefruit") is not None

        # Substring query e.g. "Grapefruit Juice 500ml"
        found = empty_repo.find_dfi("83367", "fresh Grapefruit Juice")
        assert found is not None
        assert found.rule_id == "RULE-DFI-01"

        # Non-matching food
        assert empty_repo.find_dfi("83367", "apple juice") is None

    def test_dci_prefix_matching(self, empty_repo):
        rule = DCIRule(
            rule_id="RULE-DCI-01",
            subject_rxcui="6809",
            condition_code="N18.4",
            condition_display="Stage 4 CKD",
            is_absolute_contraindication=True,
            severity=FindingSeverity.CONTRAINDICATED,
            mechanism_summary="mechanism",
            clinical_consequence="lactic acidosis",
            actionable_warning="warning",
        )
        empty_repo.add_dci_rule(rule)

        # Exact match
        assert empty_repo.find_dci("6809", "N18.4") is not None

        # Hierarchical prefix match e.g. query N18.41
        assert empty_repo.find_dci("6809", "N18.41") is not None

        # Non-matching condition
        assert empty_repo.find_dci("6809", "K27") is None

    def test_allergy_cross_matching(self, empty_repo):
        rule = AllergyRule(
            rule_id="RULE-ALLERG-01",
            allergen_group_id="ALLERG-BETA-LACTAM",
            allergen_name="Penicillin",
            cross_reactive_uniis=["804826J2HU"],  # Amoxicillin UNII
            cross_reactive_rxcuis=["723"],  # Amoxicillin RxCUI
            clinical_manifestation="Anaphylaxis",
            actionable_warning="Do not administer",
        )
        empty_repo.add_allergy_rule(rule)

        # Match via RxCUI
        found_by_rxcui = empty_repo.find_allergy_match(
            reported_allergen="Penicillin Allergy",
            target_rxcui="723",
        )
        assert found_by_rxcui is not None
        assert found_by_rxcui.rule_id == "RULE-ALLERG-01"

        # Match via UNII
        found_by_unii = empty_repo.find_allergy_match(
            reported_allergen="penicillin",
            target_uniis=["804826J2HU"],
        )
        assert found_by_unii is not None

        # Non-allergic substance
        assert (
            empty_repo.find_allergy_match(
                reported_allergen="Sulfa",
                target_rxcui="723",
            )
            is None
        )

    def test_inactive_rules_ignored(self, empty_repo):
        rule = DDIRule(
            rule_id="RULE-DDI-INACTIVE",
            subject_rxcui="111",
            interacting_rxcui="222",
            severity=FindingSeverity.MINOR,
            mechanism_summary="mechanism",
            clinical_consequence="consequence",
            actionable_warning="warning",
            status=RuleStatus.DEPRECATED,
        )
        empty_repo.add_ddi_rule(rule)
        assert empty_repo.find_ddi("111", "222") is None


class TestSeedRulesLoading:
    """Tests loading seed rules from data/seed/safety_rules.json."""

    def test_load_default_seed_rules(self):
        repo = SafetyRulesRepository()
        count = repo.load_from_json()
        assert count > 0

        stats = repo.stats()
        assert stats["ddi_count"] >= 6
        assert stats["dfi_count"] >= 4
        assert stats["dci_count"] >= 4
        assert stats["allergy_count"] >= 3
        assert stats["total_rules"] >= 17

    def test_seed_rule_queries(self):
        repo = get_safety_rules_repo()

        # Test Warfarin (11289) + Ibuprofen (5640)
        ddi = repo.find_ddi("11289", "5640")
        assert ddi is not None
        assert ddi.severity == FindingSeverity.CONTRAINDICATED

        # Test Sildenafil (136443) + Nitroglycerin (4917)
        sildenafil_nitrate = repo.find_ddi("136443", "4917")
        assert sildenafil_nitrate is not None
        assert sildenafil_nitrate.severity == FindingSeverity.CONTRAINDICATED

        # Test Atorvastatin (83367) + Grapefruit Juice
        dfi = repo.find_dfi("83367", "Grapefruit Juice")
        assert dfi is not None
        assert dfi.severity == FindingSeverity.MAJOR

        # Test Propranolol (8787) in Asthma (J45)
        dci = repo.find_dci("8787", "J45")
        assert dci is not None
        assert dci.is_absolute_contraindication is True

        # Test Penicillin allergy with Amoxicillin (RxCUI 723)
        allergy = repo.find_allergy_match("Penicillin Allergy", target_rxcui="723")
        assert allergy is not None
        assert allergy.allergen_group_id == "ALLERG-BETA-LACTAM"
