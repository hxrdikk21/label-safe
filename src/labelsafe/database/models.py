"""
Canonical PostgreSQL relational models (SQLAlchemy 2.0 typed declarative mapping).

PostgreSQL is the single source of truth: pgvector embeddings and the Neo4j
graph are derived from these tables and tracked through ``derived_sync_status``.
Array/JSON columns fall back to JSON on non-PostgreSQL dialects so the models
can be exercised against SQLite in unit tests.
"""

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.labelsafe.core.contracts.document import SourceDocument
from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.core.contracts.medication import IngredientReference, MedicationConcept
from src.labelsafe.core.contracts.product import DrugProduct

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

TextArray = ARRAY(Text).with_variant(JSON(), "sqlite")
JsonDocument = JSONB().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TargetStore(enum.StrEnum):
    PGVECTOR = "PGVECTOR"
    NEO4J = "NEO4J"


class SyncState(enum.StrEnum):
    PENDING = "PENDING"
    SYNCED = "SYNCED"
    FAILED = "FAILED"


class EntityType(enum.StrEnum):
    CONCEPT = "CONCEPT"
    PRODUCT = "PRODUCT"
    DOCUMENT = "DOCUMENT"
    PASSAGE = "PASSAGE"


class CacheEntryStatus(enum.StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"


def _enum(cls: type[enum.StrEnum], name: str) -> Enum:
    return Enum(cls, name=name, native_enum=False, length=16, validate_strings=True)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    full_name: Mapped[str | None] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="ROLE_USER", server_default="ROLE_USER")
    is_2fa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    totp_secret: Mapped[str | None] = mapped_column(String(64))


class UserBackupCode(Base):
    """One-time 2FA recovery code, stored only as an Argon2id hash."""

    __tablename__ = "user_backup_codes"

    code_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(255))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshTokenRecord(Base):
    """Issued refresh tokens by JWT id; rotation revokes the presented token."""

    __tablename__ = "refresh_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserAllergy(Base):
    """``user_allergies``: a user's recorded allergies."""

    __tablename__ = "user_allergies"

    allergy_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    substance_name: Mapped[str] = mapped_column(String(255))
    unii: Mapped[str | None] = mapped_column(String(32))
    allergy_class: Mapped[str | None] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(32), default="UNKNOWN", server_default="UNKNOWN")
    verification_source: Mapped[str] = mapped_column(
        String(64), default="USER_REPORTED", server_default="USER_REPORTED"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserCondition(Base):
    """``user_conditions``: a user's recorded conditions."""

    __tablename__ = "user_conditions"

    condition_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    condition_name: Mapped[str] = mapped_column(String(255))
    icd10_code: Mapped[str | None] = mapped_column(String(16))
    diagnosed_date: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserActiveMedication(Base):
    """The user's current regimen (``user_medication_history``, active entries)."""

    __tablename__ = "user_active_medications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    medication: Mapped[str] = mapped_column(String(255), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserHospital(Base):
    __tablename__ = "user_hospitals"

    hospital_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(128))
    address: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserDoctor(Base):
    __tablename__ = "user_doctors"

    doctor_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    specialty: Mapped[str | None] = mapped_column(String(128))
    hospital_affiliation: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserMedicalVisit(Base):
    __tablename__ = "user_medical_visits"

    visit_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    visit_date: Mapped[str] = mapped_column(String(32))
    hospital_name: Mapped[str] = mapped_column(String(255))
    doctor_name: Mapped[str] = mapped_column(String(255))
    reason_for_visit: Mapped[str] = mapped_column(Text)
    clinical_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserPrescription(Base):
    __tablename__ = "user_prescriptions"

    prescription_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    medication_name: Mapped[str] = mapped_column(String(255))
    dosage: Mapped[str | None] = mapped_column(String(128))
    prescribed_by: Mapped[str] = mapped_column(String(255))
    prescribed_date: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", server_default="ACTIVE")
    instructions: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MedicationConceptRecord(TimestampMixin, Base):
    __tablename__ = "medication_concepts"

    rxcui: Mapped[str] = mapped_column(String(32), primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    term_type: Mapped[str] = mapped_column(String(16))
    ingredients: Mapped[list[dict[str, Any]]] = mapped_column(JsonDocument, default=list)
    synonyms: Mapped[list[str]] = mapped_column(TextArray, default=list)
    jurisdiction: Mapped[str] = mapped_column(String(16), default="US", server_default="US")
    is_ambiguous: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ambiguity_candidates: Mapped[list[str]] = mapped_column(TextArray, default=list)
    priority_rank: Mapped[int | None] = mapped_column(Integer, unique=True)
    therapeutic_category: Mapped[str | None] = mapped_column(String(64))
    is_narrow_therapeutic_index: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    content_hash: Mapped[str] = mapped_column(String(64))

    products: Mapped[list["DrugProductRecord"]] = relationship(back_populates="concept")

    def to_contract(self) -> MedicationConcept:
        return MedicationConcept(
            rxcui=self.rxcui,
            canonical_name=self.canonical_name,
            term_type=self.term_type,
            ingredients=[IngredientReference.model_validate(i) for i in self.ingredients],
            synonyms=list(self.synonyms),
            jurisdiction=self.jurisdiction,
            is_ambiguous=self.is_ambiguous,
            ambiguity_candidates=list(self.ambiguity_candidates),
        )


class DrugProductRecord(Base):
    __tablename__ = "drug_products"

    ndc: Mapped[str] = mapped_column(String(32), primary_key=True)
    rxcui: Mapped[str] = mapped_column(ForeignKey("medication_concepts.rxcui"), index=True)
    brand_name: Mapped[str] = mapped_column(Text)
    generic_name: Mapped[str] = mapped_column(Text)
    dosage_form: Mapped[str] = mapped_column(String(64))
    route: Mapped[str] = mapped_column(String(64))
    strength: Mapped[str] = mapped_column(Text)
    spl_setid: Mapped[str] = mapped_column(String(64), index=True)
    rxcui_scd: Mapped[str | None] = mapped_column(String(32))
    active_ingredient_uniis: Mapped[list[str]] = mapped_column(TextArray, default=list)
    inactive_excipient_uniis: Mapped[list[str]] = mapped_column(TextArray, default=list)
    marketing_status: Mapped[str] = mapped_column(String(32), default="Prescription")
    jurisdiction: Mapped[str] = mapped_column(String(16), default="US", server_default="US")

    concept: Mapped[MedicationConceptRecord] = relationship(back_populates="products")

    @classmethod
    def from_contract(cls, product: DrugProduct) -> "DrugProductRecord":
        return cls(**product.model_dump())

    def to_contract(self) -> DrugProduct:
        return DrugProduct(
            ndc=self.ndc,
            rxcui=self.rxcui,
            brand_name=self.brand_name,
            generic_name=self.generic_name,
            dosage_form=self.dosage_form,
            route=self.route,
            strength=self.strength,
            spl_setid=self.spl_setid,
            rxcui_scd=self.rxcui_scd,
            active_ingredient_uniis=list(self.active_ingredient_uniis),
            inactive_excipient_uniis=list(self.inactive_excipient_uniis),
            marketing_status=self.marketing_status,
            jurisdiction=self.jurisdiction,
        )


class SourceDocumentRecord(Base):
    __tablename__ = "source_documents"

    document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(32))
    effective_date: Mapped[date | None] = mapped_column(Date)
    title: Mapped[str] = mapped_column(Text)
    sha256_hash: Mapped[str] = mapped_column(String(64), index=True)
    jurisdiction: Mapped[str] = mapped_column(String(16), default="US", server_default="US")
    rxcui_primary: Mapped[str | None] = mapped_column(String(32), index=True)
    missing_excipient_data: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    retrieval_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    passages: Mapped[list["EvidencePassageRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    @classmethod
    def from_contract(cls, doc: SourceDocument, *, missing_excipient_data: bool) -> "SourceDocumentRecord":
        return cls(
            document_id=doc.document_id,
            source_name=doc.source_name,
            source_url=str(doc.source_url),
            version=doc.version,
            effective_date=date.fromisoformat(doc.effective_date) if doc.effective_date else None,
            title=doc.title,
            sha256_hash=doc.sha256_hash,
            jurisdiction=doc.jurisdiction,
            rxcui_primary=doc.rxcui_primary,
            missing_excipient_data=missing_excipient_data,
            retrieval_timestamp=doc.retrieval_timestamp,
        )

    def to_contract(self) -> SourceDocument:
        return SourceDocument.model_validate(
            {
                "document_id": self.document_id,
                "source_name": self.source_name,
                "source_url": self.source_url,
                "version": self.version,
                "effective_date": self.effective_date.isoformat() if self.effective_date else None,
                "title": self.title,
                "sha256_hash": self.sha256_hash,
                "jurisdiction": self.jurisdiction,
                "rxcui_primary": self.rxcui_primary,
                "retrieval_timestamp": self.retrieval_timestamp,
            }
        )


class EvidencePassageRecord(Base):
    __tablename__ = "evidence_passages"
    __table_args__ = (
        UniqueConstraint("document_id", "loinc_section_code", "passage_index", "chunk_version"),
        Index("ix_evidence_passages_rxcui_loinc", "rxcui", "loinc_section_code"),
    )

    passage_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.document_id", ondelete="CASCADE"))
    rxcui: Mapped[str] = mapped_column(ForeignKey("medication_concepts.rxcui"))
    loinc_section_code: Mapped[str] = mapped_column(String(32))
    section_title: Mapped[str] = mapped_column(String(128))
    passage_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer)
    sha256_hash: Mapped[str] = mapped_column(String(64), index=True)
    chunk_version: Mapped[str] = mapped_column(String(16))
    embedding_status: Mapped[str] = mapped_column(String(16), default="PENDING", server_default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[SourceDocumentRecord] = relationship(back_populates="passages")

    @classmethod
    def from_contract(cls, passage: EvidencePassage) -> "EvidencePassageRecord":
        data = passage.model_dump()
        data["passage_id"] = uuid.UUID(passage.passage_id)
        return cls(**data)

    def to_contract(self) -> EvidencePassage:
        return EvidencePassage(
            passage_id=str(self.passage_id),
            document_id=self.document_id,
            rxcui=self.rxcui,
            loinc_section_code=self.loinc_section_code,
            section_title=self.section_title,
            passage_index=self.passage_index,
            content=self.content,
            token_count=self.token_count,
            sha256_hash=self.sha256_hash,
            chunk_version=self.chunk_version,
            embedding_status=self.embedding_status,
        )


class DerivedSyncStatus(Base):
    __tablename__ = "derived_sync_status"
    __table_args__ = (
        UniqueConstraint("entity_id", "target_store"),
        Index("ix_derived_sync_status_store_state", "target_store", "sync_status"),
    )

    sync_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[str] = mapped_column(String(128))
    entity_type: Mapped[EntityType] = mapped_column(_enum(EntityType, "entity_type"))
    target_store: Mapped[TargetStore] = mapped_column(_enum(TargetStore, "target_store"))
    sync_status: Mapped[SyncState] = mapped_column(_enum(SyncState, "sync_state"), default=SyncState.PENDING)
    version: Mapped[str] = mapped_column(String(64))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)
    last_attempt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RateLimitCounter(Base):
    """Events per key per fixed time window (login failures, per-IP requests, daily Gemini calls)."""

    __tablename__ = "rate_limit_counters"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    bucket: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class ExternalLookupCache(Base):
    """Local-first cache of external terminology/label lookups, including negative (404) entries."""

    __tablename__ = "external_lookup_cache"

    cache_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    status: Mapped[CacheEntryStatus] = mapped_column(_enum(CacheEntryStatus, "cache_entry_status"))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
