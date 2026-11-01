"""
Contract Test Suite for LabelSafe Canonical Contracts.
Tests validation, serialization, deserialization, immutability, and schema compliance.
"""

import pytest
from pydantic import ValidationError

from src.labelsafe.core.config import get_settings
from src.labelsafe.core.contracts.document import SourceDocument
from src.labelsafe.core.contracts.evidence import EvidencePassage, SourceEvidence
from src.labelsafe.core.contracts.medication import IngredientReference, MedicationConcept
from src.labelsafe.core.contracts.product import DrugProduct
from src.labelsafe.core.contracts.rag_response import RAGResponse, VerifiedCitation
from src.labelsafe.core.contracts.safety import FindingSeverity, FindingStatus, SafetyFinding
from src.labelsafe.core.contracts.safety_evidence import SafetyEvidence
from src.labelsafe.core.contracts.user_context import (
    UserAllergyRecord,
    UserConditionRecord,
    UserContext,
)


class TestConfigSettings:
    """Tests for system-wide configuration loading and BaseSettings."""

    def test_default_settings(self):
        settings = get_settings()
        assert settings.app_name == "LabelSafe"
        assert settings.app_version == "2.0.0"
        assert "postgresql" in type(settings).model_fields["database_url"].default
        assert settings.jwt_algorithm == "HS256"
        # 384 matches the embedding engine and pgvector column (BAAI/bge-small-en-v1.5).
        assert settings.embedding_dimension == 384
        assert settings.model_mode in ("real", "fake") and settings.llm_backend == "template"
        assert len(settings.clinical_disclaimer) > 20

    def test_settings_singleton(self):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2


class TestMedicationContracts:
    """Tests for MedicationConcept and IngredientReference."""

    def test_valid_medication_concept(self):
        ing = IngredientReference(
            unii="6Q90EBV89F",
            name="Warfarin",
            is_active=True,
            allergen_group_id=None,
        )
        med = MedicationConcept(
            rxcui="11289",
            canonical_name="Warfarin",
            term_type="IN",
            ingredients=[ing],
            synonyms=["Coumadin", "Jantoven"],
            jurisdiction="US",
            is_ambiguous=False,
        )
        assert med.rxcui == "11289"
        assert len(med.ingredients) == 1
        assert med.ingredients[0].name == "Warfarin"
        assert med.synonyms == ["Coumadin", "Jantoven"]

    def test_ambiguous_medication_concept(self):
        med = MedicationConcept(
            rxcui="6918",
            canonical_name="Metoprolol",
            term_type="IN",
            is_ambiguous=True,
            ambiguity_candidates=["866416", "866428"],
        )
        assert med.is_ambiguous is True
        assert len(med.ambiguity_candidates) == 2

    def test_ingredient_immutability(self):
        ing = IngredientReference(unii="J2B2A4N98G", name="Lactose Monohydrate", is_active=False)
        with pytest.raises(ValidationError):
            ing.name = "Modified Name"  # frozen=True

    def test_reject_extra_fields(self):
        with pytest.raises(ValidationError):
            MedicationConcept(
                rxcui="11289",
                canonical_name="Warfarin",
                term_type="IN",
                unsupported_extra_field="malicious_payload",
            )


class TestProductAndDocumentContracts:
    """Tests for DrugProduct and SourceDocument."""

    def test_valid_drug_product(self):
        prod = DrugProduct(
            ndc="0056-0170-70",
            rxcui="11289",
            brand_name="Coumadin",
            generic_name="Warfarin Sodium",
            dosage_form="Tablet",
            route="Oral",
            strength="5 mg",
            spl_setid="a3b4c5d6-e7f8-90ab-cdef-1234567890ab",
            active_ingredient_uniis=["6Q90EBV89F"],
            inactive_excipient_uniis=["J2B2A4N98G"],
        )
        assert prod.ndc == "0056-0170-70"
        assert prod.brand_name == "Coumadin"
        assert len(prod.inactive_excipient_uniis) == 1

    def test_valid_source_document(self):
        doc = SourceDocument(
            document_id="SPL-SETID-001",
            source_name="DailyMed",
            source_url="https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=001",
            version="12",
            effective_date="2025-06-10",
            title="WARFARIN SODIUM tablet [Bristol-Myers Squibb Company]",
            sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            jurisdiction="US",
        )
        assert doc.source_name == "DailyMed"
        assert str(doc.source_url).startswith("https://dailymed")

    def test_invalid_sha256_length(self):
        with pytest.raises(ValidationError):
            SourceDocument(
                document_id="SPL-SETID-001",
                source_name="DailyMed",
                source_url="https://dailymed.nlm.nih.gov",
                version="1",
                title="Sample Drug",
                sha256_hash="short_hash_less_than_64_chars",
            )


class TestEvidenceAndSafetyContracts:
    """Tests for EvidencePassage, SourceEvidence, SafetyEvidence, and SafetyFinding."""

    def test_evidence_passage_and_source_evidence(self):
        passage = EvidencePassage(
            passage_id="PASS-001",
            document_id="SPL-001",
            rxcui="11289",
            loinc_section_code="34073-7",
            section_title="DRUG INTERACTIONS",
            passage_index=42,
            content="Concomitant use of NSAIDs with Warfarin increases bleeding risk.",
            token_count=12,
            sha256_hash="a" * 64,
            chunk_version="1.0.0",
            embedding_status="INDEXED",
        )
        assert passage.passage_index == 42
        assert passage.embedding_status == "INDEXED"

        evidence = SourceEvidence(
            evidence_id="EV-001",
            passage_id="PASS-001",
            source_name="DailyMed",
            source_url="https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=001",
            document_id="SPL-001",
            rxcui="11289",
            section_title="DRUG INTERACTIONS",
            supporting_passage=passage.content,
            source_version="12",
            relevance_score=0.94,
        )
        assert evidence.relevance_score == 0.94

    def test_safety_evidence_relation(self):
        rel = SafetyEvidence(
            evidence_id="SE-001",
            passage_id="PASS-001",
            finding_type="DDI",
            involved_rxcuis=["11289", "5640"],
            qualifiers=["avoid concurrent use"],
            verification_status="VERIFIED",
        )
        assert len(rel.involved_rxcuis) == 2
        assert rel.verification_status == "VERIFIED"

    def test_safety_finding_enums(self):
        finding = SafetyFinding(
            finding_id="FINDING-001",
            finding_type="DRUG_DRUG_INTERACTION",
            subject_medications=["11289", "5640"],
            status=FindingStatus.RISK_IDENTIFIED,
            severity=FindingSeverity.CONTRAINDICATED,
            rule_id="RULE-DDI-001",
            supporting_evidence_ids=["PASS-001"],
            clinical_explanation="Synergistic platelet inhibition and vitamin K antagonism.",
            actionable_warning="Do not co-prescribe Warfarin and Ibuprofen without hematology oversight.",
            requires_professional_review=True,
        )
        assert finding.status == FindingStatus.RISK_IDENTIFIED
        assert finding.severity == FindingSeverity.CONTRAINDICATED
        assert finding.requires_professional_review is True

    def test_invalid_status_enum(self):
        with pytest.raises(ValidationError):
            SafetyFinding(
                finding_id="F-001",
                finding_type="DDI",
                subject_medications=["11289"],
                status="safe_and_harmless",  # Invalid enum value!
                clinical_explanation="explanation",
                actionable_warning="warning",
            )


class TestRAGResponseAndUserContext:
    """Tests for RAGResponse, VerifiedCitation, and UserContext."""

    def test_rag_response_round_trip(self):
        citation = VerifiedCitation(
            citation_id="CITE-001",
            passage_id="PASS-001",
            cited_sentence="Co-administration of Warfarin and Ibuprofen increases hemorrhage risk.",
            entailment_score=0.98,
            verification_status="VERIFIED",
        )
        finding = SafetyFinding(
            finding_id="FINDING-001",
            finding_type="DRUG_DRUG_INTERACTION",
            subject_medications=["11289", "5640"],
            status=FindingStatus.RISK_IDENTIFIED,
            severity=FindingSeverity.CONTRAINDICATED,
            clinical_explanation="Severe bleeding risk.",
            actionable_warning="Avoid combination.",
        )
        resp = RAGResponse(
            response_id="RESP-001",
            findings=[finding],
            grounded_narrative="Warfarin interacts with Ibuprofen significantly.",
            verified_citations=[citation],
            unresolved_questions=[],
            evidence_sufficiency_state="SUFFICIENT",
            missing_data_warnings=[],
            disclaimer="Research prototype only.",
        )
        # Verify JSON serialization round-trip
        json_data = resp.model_dump_json()
        restored = RAGResponse.model_validate_json(json_data)
        assert restored.response_id == "RESP-001"
        assert len(restored.verified_citations) == 1
        assert restored.verified_citations[0].entailment_score == 0.98

    def test_user_context_and_allergies(self):
        allergy = UserAllergyRecord(
            substance_name="Penicillin V",
            unii="Q42T66VG0C",
            allergy_class="Beta-Lactam",
            severity="SEVERE_ANAPHYLAXIS",
            verification_source="CLINICIAN_VERIFIED",
        )
        condition = UserConditionRecord(
            condition_name="Peptic Ulcer Disease",
            icd10_code="K27",
            diagnosed_date="2024-01-15",
        )
        user = UserContext(
            user_id="USER-UUID-001",
            roles=["ROLE_USER"],
            active_medications=["Warfarin 5mg daily"],
            allergies=[allergy],
            conditions=[condition],
            emergency_contacts_enabled=True,
        )
        assert user.user_id == "USER-UUID-001"
        assert user.roles == ["ROLE_USER"]
        assert user.allergies[0].severity == "SEVERE_ANAPHYLAXIS"
        assert user.conditions[0].icd10_code == "K27"
        assert user.emergency_contacts_enabled is True
