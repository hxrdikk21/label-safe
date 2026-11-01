"""drug_products: label free text (names, strength) has no length limit.

A homeopathic SPL with ~40 ingredients overflowed VARCHAR(255) and aborted ingestion.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None

COLUMNS = {"brand_name": 255, "generic_name": 255, "strength": 128}


def upgrade() -> None:
    for column in COLUMNS:
        op.alter_column("drug_products", column, type_=sa.Text())


def downgrade() -> None:
    for column, length in COLUMNS.items():
        op.alter_column("drug_products", column, type_=sa.String(length))
