"""
RAG response and verified citation contracts.
Defines the grounded natural language explanation, citation audit trail, and uncertainty disclosures.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .safety import SafetyFinding


class VerifiedCitation(BaseModel):
    """A generated sentence and the retrieved passage it cites (deterministic check, no NLI model)."""

    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(..., min_length=1, description="Unique UUID for this citation reference")
    passage_id: str = Field(..., min_length=1, description="Associated EvidencePassage passage_id")
    cited_sentence: str = Field(..., min_length=1, description="Exact generated sentence being checked")
    entailment_score: float = Field(
        ..., ge=0.0, le=1.0, description="1.0 when the sentence cites a retrieved passage, else 0.0"
    )
    verification_status: str = Field(..., description="VERIFIED (cites a retrieved passage) or UNVERIFIED")


class LabelSource(BaseModel):
    """A drug-label passage an answer cites, ready to show: drug, section, a short quote and its link."""

    passage_id: str
    drug: str
    section: str
    quote: str
    url: str


class FindingExplanation(BaseModel):
    """One safety finding explained from its own label passages (text None: no label text found)."""

    finding_id: str
    text: str | None = None
    sources: list[LabelSource] = Field(default_factory=list)
    mode: Literal["gemini", "offline"] = "offline"


class RAGResponse(BaseModel):
    """Unified evidence-grounded response returned to API consumers."""

    model_config = ConfigDict(extra="forbid")

    response_id: str = Field(..., min_length=1, description="Unique correlation ID for the response")
    request_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="UTC timestamp of response generation"
    )
    findings: list[SafetyFinding] = Field(
        default_factory=list, description="List of deterministic and neural safety findings"
    )
    grounded_narrative: str = Field(
        ..., min_length=1, description="Natural language explanation synthesized from retrieved passages"
    )
    verified_citations: list[VerifiedCitation] = Field(
        default_factory=list, description="Audit list of sentence-level citations with entailment scores"
    )
    sources: list[LabelSource] = Field(
        default_factory=list, description="Cited label passages in order of first citation"
    )
    unresolved_questions: list[str] = Field(
        default_factory=list, description="Clinical questions or ambiguities that could not be resolved"
    )
    evidence_sufficiency_state: str = Field(
        default="SUFFICIENT", description="SUFFICIENT, PARTIAL, INSUFFICIENT"
    )
    missing_data_warnings: list[str] = Field(
        default_factory=list, description="Explicit disclosures for missing labels, excipients, or history"
    )
    disclaimer: str = Field(..., min_length=1, description="Mandatory medical safety disclaimer")
