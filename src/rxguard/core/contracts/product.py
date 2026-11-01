"""
Drug product formulation contracts.
Canonical schema representing specific commercial package formulations.
"""

from pydantic import BaseModel, ConfigDict, Field


class DrugProduct(BaseModel):
    """Specific commercial formulation and packaging of a clinical drug product."""

    model_config = ConfigDict(extra="forbid")

    ndc: str = Field(..., min_length=1, description="National Drug Code (e.g. 0056-0170-70)")
    rxcui: str = Field(..., min_length=1, description="Associated canonical MedicationConcept RxCUI")
    brand_name: str = Field(..., min_length=1, description="Commercial proprietary name")
    generic_name: str = Field(..., min_length=1, description="Non-proprietary generic substance name")
    dosage_form: str = Field(..., description="Dosage form e.g. Tablet, Capsule, Solution")
    route: str = Field(..., description="Route of administration e.g. Oral, Intravenous")
    strength: str = Field(..., description="Dose strength e.g. 5 mg, 500 mg/5 mL")
    spl_setid: str = Field(..., min_length=1, description="DailyMed SPL SetID identifier")
    rxcui_scd: str | None = Field(default=None, description="RxNorm Semantic Clinical Drug (SCD) concept ID")
    active_ingredient_uniis: list[str] = Field(
        default_factory=list, description="List of active moiety FDA UNIIs"
    )
    inactive_excipient_uniis: list[str] = Field(
        default_factory=list, description="List of inactive excipient FDA UNIIs"
    )
    marketing_status: str = Field(default="Prescription", description="Prescription, OTC, Discontinued")
    jurisdiction: str = Field(default="US", description="Regulatory jurisdiction")
