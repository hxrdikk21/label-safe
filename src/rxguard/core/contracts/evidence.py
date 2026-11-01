"""
Evidence passage and retrieval evidence contracts.
Schemas representing chunked label passages and ranked evidence candidates.
"""

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class EvidencePassage(BaseModel):
    """Atomic text passage extracted from a regulatory document and stored for retrieval."""

    model_config = ConfigDict(extra="forbid")

    passage_id: str = Field(..., min_length=1, description="Unique UUID identifier for the passage chunk")
    document_id: str = Field(..., min_length=1, description="Associated SourceDocument identifier")
    rxcui: str = Field(..., min_length=1, description="Associated medication concept RxCUI")
    loinc_section_code: str = Field(..., description="Standard LOINC code e.g. 34073-7 for interactions")
    section_title: str = Field(..., description="Human-readable section title")
    passage_index: int = Field(..., ge=0, description="Sequential index within document section")
    content: str = Field(..., min_length=1, description="Raw text content of the clinical chunk")
    token_count: int | None = Field(default=None, ge=0, description="Token length of the passage")
    sha256_hash: str = Field(..., min_length=64, max_length=64, description="SHA-256 digest of passage text")
    chunk_version: str = Field(default="1.0.0", description="Chunking algorithm version string")
    embedding_status: str = Field(default="PENDING", description="INDEXED, PENDING, FAILED")


class SourceEvidence(BaseModel):
    """Ranked evidence passage returned by hybrid retrieval and cross-encoder reranking."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(..., min_length=1, description="Unique identifier for this retrieval instance")
    passage_id: str = Field(..., min_length=1, description="Underlying EvidencePassage passage_id")
    source_name: str = Field(..., description="DailyMed, openFDA, RxNav, CDSCO")
    source_url: HttpUrl = Field(..., description="Canonical source URL")
    document_id: str = Field(..., description="SPL SetID or FDA document ID")
    rxcui: str = Field(..., description="Associated normalized drug RxCUI")
    loinc_section_code: str | None = Field(default=None, description="Standard LOINC code")
    section_title: str = Field(..., description="Section title e.g. DRUG INTERACTIONS")
    supporting_passage: str = Field(..., min_length=1, description="Exact clinical text snippet")
    passage_index: int = Field(default=0, ge=0)
    jurisdiction: str = Field(default="US", description="Regulatory jurisdiction")
    source_version: str = Field(..., description="Source document version/revision")
    relevance_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Normalized relevance score from reranker"
    )
