"""Workstream 1 canonical schema: users, concepts, products, documents, passages, sync status, lookup cache.

Revision ID: 0001
Revises:
Create Date: 2026-10-15 23:21:42.822436
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "derived_sync_status",
        sa.Column("sync_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=False),
        sa.Column(
            "entity_type",
            sa.Enum(
                "CONCEPT", "PRODUCT", "DOCUMENT", "PASSAGE", name="entity_type", native_enum=False, length=16
            ),
            nullable=False,
        ),
        sa.Column(
            "target_store",
            sa.Enum("PGVECTOR", "NEO4J", name="target_store", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column(
            "sync_status",
            sa.Enum("PENDING", "SYNCED", "FAILED", name="sync_state", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("last_attempt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("sync_id", name=op.f("pk_derived_sync_status")),
        sa.UniqueConstraint("entity_id", "target_store", name=op.f("uq_derived_sync_status_entity_id")),
    )
    op.create_index(
        "ix_derived_sync_status_store_state",
        "derived_sync_status",
        ["target_store", "sync_status"],
        unique=False,
    )
    op.create_table(
        "external_lookup_cache",
        sa.Column("cache_key", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum("POSITIVE", "NEGATIVE", name="cache_entry_status", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("cache_key", name=op.f("pk_external_lookup_cache")),
    )
    op.create_index(
        op.f("ix_external_lookup_cache_expires_at"), "external_lookup_cache", ["expires_at"], unique=False
    )
    op.create_table(
        "medication_concepts",
        sa.Column("rxcui", sa.String(length=32), nullable=False),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("term_type", sa.String(length=16), nullable=False),
        sa.Column("ingredients", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("synonyms", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("jurisdiction", sa.String(length=16), server_default="US", nullable=False),
        sa.Column("is_ambiguous", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("ambiguity_candidates", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("priority_rank", sa.Integer(), nullable=True),
        sa.Column("therapeutic_category", sa.String(length=64), nullable=True),
        sa.Column("is_narrow_therapeutic_index", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("rxcui", name=op.f("pk_medication_concepts")),
        sa.UniqueConstraint("priority_rank", name=op.f("uq_medication_concepts_priority_rank")),
    )
    op.create_index(
        op.f("ix_medication_concepts_canonical_name"), "medication_concepts", ["canonical_name"], unique=False
    )
    op.create_table(
        "source_documents",
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("sha256_hash", sa.String(length=64), nullable=False),
        sa.Column("jurisdiction", sa.String(length=16), server_default="US", nullable=False),
        sa.Column("rxcui_primary", sa.String(length=32), nullable=True),
        sa.Column("missing_excipient_data", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "retrieval_timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("document_id", name=op.f("pk_source_documents")),
    )
    op.create_index(
        op.f("ix_source_documents_rxcui_primary"), "source_documents", ["rxcui_primary"], unique=False
    )
    op.create_index(
        op.f("ix_source_documents_sha256_hash"), "source_documents", ["sha256_hash"], unique=False
    )
    op.create_table(
        "users",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="ROLE_USER", nullable=False),
        sa.Column("is_2fa_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("totp_secret", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "drug_products",
        sa.Column("ndc", sa.String(length=32), nullable=False),
        sa.Column("rxcui", sa.String(length=32), nullable=False),
        sa.Column("brand_name", sa.String(length=255), nullable=False),
        sa.Column("generic_name", sa.String(length=255), nullable=False),
        sa.Column("dosage_form", sa.String(length=64), nullable=False),
        sa.Column("route", sa.String(length=64), nullable=False),
        sa.Column("strength", sa.String(length=128), nullable=False),
        sa.Column("spl_setid", sa.String(length=64), nullable=False),
        sa.Column("rxcui_scd", sa.String(length=32), nullable=True),
        sa.Column("active_ingredient_uniis", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("inactive_excipient_uniis", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("marketing_status", sa.String(length=32), nullable=False),
        sa.Column("jurisdiction", sa.String(length=16), server_default="US", nullable=False),
        sa.ForeignKeyConstraint(
            ["rxcui"], ["medication_concepts.rxcui"], name=op.f("fk_drug_products_rxcui_medication_concepts")
        ),
        sa.PrimaryKeyConstraint("ndc", name=op.f("pk_drug_products")),
    )
    op.create_index(op.f("ix_drug_products_rxcui"), "drug_products", ["rxcui"], unique=False)
    op.create_index(op.f("ix_drug_products_spl_setid"), "drug_products", ["spl_setid"], unique=False)
    op.create_table(
        "evidence_passages",
        sa.Column("passage_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("rxcui", sa.String(length=32), nullable=False),
        sa.Column("loinc_section_code", sa.String(length=32), nullable=False),
        sa.Column("section_title", sa.String(length=128), nullable=False),
        sa.Column("passage_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("sha256_hash", sa.String(length=64), nullable=False),
        sa.Column("chunk_version", sa.String(length=16), nullable=False),
        sa.Column("embedding_status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["source_documents.document_id"],
            name=op.f("fk_evidence_passages_document_id_source_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rxcui"],
            ["medication_concepts.rxcui"],
            name=op.f("fk_evidence_passages_rxcui_medication_concepts"),
        ),
        sa.PrimaryKeyConstraint("passage_id", name=op.f("pk_evidence_passages")),
        sa.UniqueConstraint(
            "document_id",
            "loinc_section_code",
            "passage_index",
            "chunk_version",
            name=op.f("uq_evidence_passages_document_id"),
        ),
    )
    op.create_index(
        "ix_evidence_passages_rxcui_loinc", "evidence_passages", ["rxcui", "loinc_section_code"], unique=False
    )
    op.create_index(
        op.f("ix_evidence_passages_sha256_hash"), "evidence_passages", ["sha256_hash"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_evidence_passages_sha256_hash"), table_name="evidence_passages")
    op.drop_index("ix_evidence_passages_rxcui_loinc", table_name="evidence_passages")
    op.drop_table("evidence_passages")
    op.drop_index(op.f("ix_drug_products_spl_setid"), table_name="drug_products")
    op.drop_index(op.f("ix_drug_products_rxcui"), table_name="drug_products")
    op.drop_table("drug_products")
    op.drop_table("users")
    op.drop_index(op.f("ix_source_documents_sha256_hash"), table_name="source_documents")
    op.drop_index(op.f("ix_source_documents_rxcui_primary"), table_name="source_documents")
    op.drop_table("source_documents")
    op.drop_index(op.f("ix_medication_concepts_canonical_name"), table_name="medication_concepts")
    op.drop_table("medication_concepts")
    op.drop_index(op.f("ix_external_lookup_cache_expires_at"), table_name="external_lookup_cache")
    op.drop_table("external_lookup_cache")
    op.drop_index("ix_derived_sync_status_store_state", table_name="derived_sync_status")
    op.drop_table("derived_sync_status")
