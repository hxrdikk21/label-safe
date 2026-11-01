"""
Medication and ingredient identity contracts.
Canonical schemas shared across ingestion, normalization, safety engine, and graph layers.
"""

from pydantic import BaseModel, ConfigDict, Field


class IngredientReference(BaseModel):
    """Normalized active moiety or inactive excipient substance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unii: str = Field(..., min_length=1, description="FDA Unique Ingredient Identifier")
    name: str = Field(..., min_length=1, description="Normalized chemical substance name")
    is_active: bool = Field(default=True, description="True for active moiety, False for inactive excipient")
    allergen_group_id: str | None = Field(
        default=None, description="Optional cross-referenced allergen group identifier"
    )


class MedicationConcept(BaseModel):
    """Canonical medication concept representing a clinical entity in the terminology catalog."""

    model_config = ConfigDict(extra="forbid")

    rxcui: str = Field(..., min_length=1, description="RxNorm Concept Unique Identifier")
    canonical_name: str = Field(..., min_length=1, description="Normalized generic or clinical brand name")
    term_type: str = Field(..., min_length=1, description="RxNorm Term Type (e.g., IN, PIN, SCD, SBD)")
    ingredients: list[IngredientReference] = Field(
        default_factory=list, description="Active moieties and identified excipients"
    )
    synonyms: list[str] = Field(default_factory=list, description="Common commercial brand names and aliases")
    jurisdiction: str = Field(default="US", description="Regulatory jurisdiction e.g. US, IN, GLOBAL")
    is_ambiguous: bool = Field(
        default=False, description="True if query resolved to multiple distinct formulations"
    )
    ambiguity_candidates: list[str] = Field(
        default_factory=list, description="Candidate RxCUIs or formulations when ambiguous"
    )
