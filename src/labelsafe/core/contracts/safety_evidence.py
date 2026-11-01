"""
Structured safety evidence relation contracts.
Represents an extracted, source-backed relationship between clinical entities and regulatory passages.
"""

from pydantic import BaseModel, ConfigDict, Field


class SafetyEvidence(BaseModel):
    """Clinical safety evidence binding a regulatory passage to specific clinical entities."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(..., min_length=1, description="Unique identifier for this safety evidence link")
    passage_id: str = Field(..., min_length=1, description="Associated EvidencePassage UUID")
    finding_type: str = Field(..., description="DDI, DFI, DCI, ALLERGY, WARNING, PRECAUTION")
    involved_rxcuis: list[str] = Field(..., min_length=1, description="List of involved medication RxCUIs")
    condition_icd10: str | None = Field(default=None, description="Associated ICD-10 condition code if DCI")
    food_identifier: str | None = Field(default=None, description="Associated dietary/food item name if DFI")
    substance_unii: str | None = Field(
        default=None, description="Associated chemical substance UNII if allergy/excipient"
    )
    qualifiers: list[str] = Field(
        default_factory=list,
        description="Administration or timing qualifiers e.g. 'take 2 hours before food'",
    )
    verification_status: str = Field(default="VERIFIED", description="VERIFIED, CONTRADICTED, UNASSESSED")
