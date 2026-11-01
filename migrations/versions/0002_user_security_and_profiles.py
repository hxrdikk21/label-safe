"""User security and clinical profiles: backup codes, refresh tokens, allergies, conditions, regimen.

Also makes users.email optional (registration does not require one).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-16 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _user_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["user_id"], ["users.user_id"], name=op.f(f"fk_{table}_user_id_users"), ondelete="CASCADE"
    )


def upgrade() -> None:
    op.alter_column("users", "email", existing_type=sa.String(length=255), nullable=True)

    op.create_table(
        "user_backup_codes",
        sa.Column("code_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        _user_fk("user_backup_codes"),
        sa.PrimaryKeyConstraint("code_id", name=op.f("pk_user_backup_codes")),
    )
    op.create_index(op.f("ix_user_backup_codes_user_id"), "user_backup_codes", ["user_id"])

    op.create_table(
        "refresh_tokens",
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _user_fk("refresh_tokens"),
        sa.PrimaryKeyConstraint("jti", name=op.f("pk_refresh_tokens")),
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"])

    op.create_table(
        "user_allergies",
        sa.Column("allergy_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("substance_name", sa.String(length=255), nullable=False),
        sa.Column("unii", sa.String(length=32), nullable=True),
        sa.Column("allergy_class", sa.String(length=128), nullable=True),
        sa.Column("severity", sa.String(length=32), server_default="UNKNOWN", nullable=False),
        sa.Column(
            "verification_source", sa.String(length=64), server_default="USER_REPORTED", nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        _user_fk("user_allergies"),
        sa.PrimaryKeyConstraint("allergy_id", name=op.f("pk_user_allergies")),
    )
    op.create_index(op.f("ix_user_allergies_user_id"), "user_allergies", ["user_id"])

    op.create_table(
        "user_conditions",
        sa.Column("condition_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("condition_name", sa.String(length=255), nullable=False),
        sa.Column("icd10_code", sa.String(length=16), nullable=True),
        sa.Column("diagnosed_date", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        _user_fk("user_conditions"),
        sa.PrimaryKeyConstraint("condition_id", name=op.f("pk_user_conditions")),
    )
    op.create_index(op.f("ix_user_conditions_user_id"), "user_conditions", ["user_id"])

    op.create_table(
        "user_active_medications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("medication", sa.String(length=255), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        _user_fk("user_active_medications"),
        sa.PrimaryKeyConstraint("user_id", "medication", name=op.f("pk_user_active_medications")),
    )


def downgrade() -> None:
    op.drop_table("user_active_medications")
    op.drop_index(op.f("ix_user_conditions_user_id"), table_name="user_conditions")
    op.drop_table("user_conditions")
    op.drop_index(op.f("ix_user_allergies_user_id"), table_name="user_allergies")
    op.drop_table("user_allergies")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(op.f("ix_user_backup_codes_user_id"), table_name="user_backup_codes")
    op.drop_table("user_backup_codes")
    op.alter_column("users", "email", existing_type=sa.String(length=255), nullable=False)
