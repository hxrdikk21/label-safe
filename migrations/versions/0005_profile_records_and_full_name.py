"""users.full_name and the profile's hospitals, doctors, visits and prescriptions.

The models arrived with the auth (de02c93) and medical-profile (085874b) commits without a migration.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None


def _owned(name: str, pk: str, *columns: sa.Column) -> None:
    op.create_table(
        name,
        sa.Column(pk, sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        *columns,
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(f"ix_{name}_user_id", name, ["user_id"])


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.String(128)))
    _owned(
        "user_hospitals",
        "hospital_id",
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("department", sa.String(128)),
        sa.Column("address", sa.String(255)),
        sa.Column("phone", sa.String(64)),
    )
    _owned(
        "user_doctors",
        "doctor_id",
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("specialty", sa.String(128)),
        sa.Column("hospital_affiliation", sa.String(255)),
        sa.Column("contact_phone", sa.String(64)),
    )
    _owned(
        "user_medical_visits",
        "visit_id",
        sa.Column("visit_date", sa.String(32), nullable=False),
        sa.Column("hospital_name", sa.String(255), nullable=False),
        sa.Column("doctor_name", sa.String(255), nullable=False),
        sa.Column("reason_for_visit", sa.Text(), nullable=False),
        sa.Column("clinical_notes", sa.Text()),
    )
    _owned(
        "user_prescriptions",
        "prescription_id",
        sa.Column("medication_name", sa.String(255), nullable=False),
        sa.Column("dosage", sa.String(128)),
        sa.Column("prescribed_by", sa.String(255), nullable=False),
        sa.Column("prescribed_date", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="ACTIVE", nullable=False),
        sa.Column("instructions", sa.Text()),
    )


def downgrade() -> None:
    for name in ("user_prescriptions", "user_medical_visits", "user_doctors", "user_hospitals"):
        op.drop_table(name)
    op.drop_column("users", "full_name")
