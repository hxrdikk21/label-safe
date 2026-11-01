"""
Regulatory source document contracts.
Schema representing authoritative regulatory package inserts ingested into the system.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class SourceDocument(BaseModel):
    """Authoritative regulatory drug labeling document (e.g. DailyMed SPL XML or openFDA record)."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(..., min_length=1, description="DailyMed SPL SetID or openFDA Application ID")
    source_name: str = Field(..., min_length=1, description="DailyMed, openFDA, RxNav, CDSCO")
    source_url: HttpUrl = Field(..., description="Canonical URL to the official regulatory source")
    version: str = Field(..., description="Regulatory version or revision string")
    effective_date: str | None = Field(default=None, description="Regulatory revision date (YYYY-MM-DD)")
    title: str = Field(..., description="Full label product title")
    sha256_hash: str = Field(..., min_length=64, max_length=64, description="SHA-256 content digest")
    jurisdiction: str = Field(default="US", description="Regulatory jurisdiction e.g. US, IN, GLOBAL")
    rxcui_primary: str | None = Field(default=None, description="Primary mapped medication concept RxCUI")
    retrieval_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="UTC timestamp when document was fetched"
    )
