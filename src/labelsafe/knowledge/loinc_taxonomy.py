"""
LOINC clinical section taxonomy for Structured Product Labeling (SPL).
Defines the label sections LabelSafe extracts and indexes as evidence.
"""

from dataclasses import dataclass
from typing import Final

LOINC_CODE_SYSTEM: Final = "2.16.840.1.113883.6.1"


@dataclass(frozen=True, slots=True)
class LoincSection:
    """A clinically relevant SPL section identified by its LOINC code."""

    code: str
    title: str
    openfda_field: str


BOXED_WARNING: Final = LoincSection("34066-1", "BOXED WARNING", "boxed_warning")
CONTRAINDICATIONS: Final = LoincSection("34070-3", "CONTRAINDICATIONS", "contraindications")
DRUG_INTERACTIONS: Final = LoincSection("34073-7", "DRUG INTERACTIONS", "drug_interactions")
WARNINGS_AND_PRECAUTIONS: Final = LoincSection("43685-7", "WARNINGS AND PRECAUTIONS", "warnings_and_cautions")
INACTIVE_INGREDIENTS: Final = LoincSection("51727-6", "INACTIVE INGREDIENTS", "inactive_ingredient")

TARGET_SECTIONS: Final[tuple[LoincSection, ...]] = (
    BOXED_WARNING,
    CONTRAINDICATIONS,
    DRUG_INTERACTIONS,
    WARNINGS_AND_PRECAUTIONS,
    INACTIVE_INGREDIENTS,
)

SECTIONS_BY_CODE: Final[dict[str, LoincSection]] = {s.code: s for s in TARGET_SECTIONS}


def is_target_section(code: str | None) -> bool:
    """Returns True if the LOINC code is one of the sections LabelSafe indexes."""
    return code is not None and code in SECTIONS_BY_CODE


def section_title(code: str) -> str:
    """Returns the canonical title for a target LOINC code."""
    return SECTIONS_BY_CODE[code].title
