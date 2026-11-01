"""
Deterministic safety finding contracts.
Enforces typed severity, clinical status states, and structured clinical findings.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class FindingSeverity(str, Enum):
    """Sourced clinical severity categories. Never invented by an LLM."""

    CONTRAINDICATED = "CONTRAINDICATED"
    MAJOR = "MAJOR"
    MODERATE = "MODERATE"
    MINOR = "MINOR"
    PRECAUTION = "PRECAUTION"
    UNKNOWN_SEVERITY = "UNKNOWN_SEVERITY"


class FindingStatus(str, Enum):
    """Structured clinical finding states. Absence of evidence is NEVER equated with safety."""

    RISK_IDENTIFIED = "risk_identified"
    NO_ISSUE_FOUND_IN_CHECKED_SOURCES = "no_issue_found_in_checked_sources"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    AMBIGUOUS_MEDICATION_IDENTITY = "ambiguous_medication_identity"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    REQUIRES_PROFESSIONAL_REVIEW = "requires_professional_review"
    CHECK_UNAVAILABLE = "check_unavailable"


class SafetyFinding(BaseModel):
    """Deterministic or verified clinical finding produced by Layer C and Layer D."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(..., min_length=1, description="Unique UUID for this clinical finding")
    finding_type: str = Field(
        ..., description="DRUG_DRUG_INTERACTION, DRUG_FOOD_INTERACTION, CONTRAINDICATION, ALLERGY_EXCIPIENT"
    )
    subject_medications: list[str] = Field(
        ..., min_length=1, description="List of involved medication RxCUIs or identifiers"
    )
    status: FindingStatus = Field(..., description="Structured status state")
    severity: FindingSeverity = Field(
        default=FindingSeverity.UNKNOWN_SEVERITY, description="Clinically documented severity"
    )
    rule_id: str | None = Field(
        default=None, description="Deterministic rule ID if matched against verified symbolic rules"
    )
    supporting_evidence_ids: list[str] = Field(
        default_factory=list, description="Associated EvidencePassage IDs"
    )
    clinical_explanation: str = Field(
        ..., min_length=1, description="Detailed pharmacological consequence and rationale"
    )
    actionable_warning: str = Field(
        ..., min_length=1, description="Actionable clinical guidance e.g. 'Avoid concurrent use'"
    )
    requires_professional_review: bool = Field(default=True, description="Always True for prototype findings")
    rule_source: str | None = Field(
        default=None, description="curated, ddinter or fda_label; None for findings that need no rule"
    )
