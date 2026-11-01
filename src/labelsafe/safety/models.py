"""
Deterministic safety rule models.
Defines symbolic, source-backed rule structures for DDI, DFI, DCI, and allergy matching.
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.labelsafe.core.contracts.safety import FindingSeverity


class RuleStatus(str, Enum):
    """Lifecycle status of a clinical safety rule."""

    ACTIVE = "ACTIVE"
    DRAFT = "DRAFT"
    DEPRECATED = "DEPRECATED"
    UNDER_REVIEW = "UNDER_REVIEW"


class BaseSafetyRule(BaseModel):
    """Abstract base contract for symbolic, evidence-grounded clinical safety rules."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(..., min_length=1, description="Unique identifier for the rule (e.g. RULE-DDI-001)")
    severity: FindingSeverity = Field(..., description="Standardized clinical severity")
    mechanism_summary: str = Field(
        ..., min_length=1, description="Pharmacological or pharmacokinetic mechanism"
    )
    clinical_consequence: str = Field(
        ..., min_length=1, description="Pathophysiological risk and adverse event"
    )
    actionable_warning: str = Field(
        ..., min_length=1, description="Explicit clinical guidance for prescribers"
    )
    source_document_ids: list[str] = Field(
        default_factory=list, description="Associated DailyMed SPL SetIDs or regulatory document IDs"
    )
    status: RuleStatus = Field(default=RuleStatus.ACTIVE, description="Rule review and activation status")
    version: str = Field(default="1.0.0", description="SemVer rule definition version")
    rule_source: Literal["curated", "ddinter", "fda_label"] = Field(
        default="curated", description="curated rulebook, DDInter dataset, or extracted from FDA label text"
    )
    reviewed: bool = Field(default=True, description="False for generated rules not clinically reviewed")


class DDIRule(BaseSafetyRule):
    """Pairwise Drug-Drug Interaction rule definition."""

    subject_rxcui: str = Field(..., min_length=1, description="Primary drug RxCUI")
    interacting_rxcui: str = Field(..., min_length=1, description="Interacting drug RxCUI")
    subject_name: str | None = Field(default=None, description="Human-readable drug A name")
    interacting_name: str | None = Field(default=None, description="Human-readable drug B name")


class DFIRule(BaseSafetyRule):
    """Drug-Food Interaction rule definition."""

    subject_rxcui: str = Field(..., min_length=1, description="Drug RxCUI")
    subject_name: str | None = Field(default=None, description="Human-readable drug name")
    food_identifier: str = Field(
        ..., min_length=1, description="Normalized food/dietary item (e.g. grapefruit, dairy, alcohol)"
    )
    food_aliases: list[str] = Field(
        default_factory=list, description="Everyday names that mean this item (e.g. milk, yogurt for dairy)"
    )
    timing_qualifier: str | None = Field(
        default=None, description="Administration instructions e.g. 'Take 2 hours before or 4 hours after'"
    )


class DCIRule(BaseSafetyRule):
    """Drug-Condition Contraindication rule definition."""

    subject_rxcui: str = Field(..., min_length=1, description="Drug RxCUI")
    subject_name: str | None = Field(default=None, description="Human-readable drug name")
    condition_code: str = Field(
        ..., min_length=1, description="ICD-10-CM or SNOMED condition code (e.g. K27, J45)"
    )
    condition_display: str = Field(
        ..., min_length=1, description="Condition clinical name (e.g. Peptic Ulcer Disease, Asthma)"
    )
    additional_codes: list[str] = Field(
        default_factory=list, description="Further ICD-10 codes the rule covers (e.g. N18.5, N18.6)"
    )
    is_absolute_contraindication: bool = Field(
        default=True,
        description="True for absolute contraindication (Boxed/Section 4); False for precaution/warning",
    )


class AllergyRule(BaseModel):
    """Allergy and excipient cross-reactivity rule definition."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(..., min_length=1, description="Unique identifier for allergy rule")
    allergen_group_id: str = Field(
        ..., min_length=1, description="Allergen classification group e.g. ALLERG-BETA-LACTAM"
    )
    allergen_name: str = Field(
        ..., min_length=1, description="Common allergen category name e.g. Penicillins"
    )
    cross_reactive_uniis: list[str] = Field(
        default_factory=list, description="Substance UNIIs triggering cross-sensitivity"
    )
    cross_reactive_rxcuis: list[str] = Field(
        default_factory=list, description="Medication RxCUIs triggering cross-sensitivity"
    )
    risk_level: str = Field(default="HIGH", description="HIGH, MODERATE, LOW")
    clinical_manifestation: str = Field(
        ..., min_length=1, description="Expected symptoms e.g. Anaphylaxis, Bronchospasm, Urticaria"
    )
    actionable_warning: str = Field(..., min_length=1, description="Clinical action e.g. 'Do not administer'")
    source_document_ids: list[str] = Field(default_factory=list)
    status: RuleStatus = Field(default=RuleStatus.ACTIVE)
    version: str = Field(default="1.0.0")
    rule_source: Literal["curated", "ddinter", "fda_label"] = Field(
        default="curated", description="curated rulebook, DDInter dataset, or extracted from FDA label text"
    )
    reviewed: bool = Field(default=True, description="False for generated rules not clinically reviewed")
