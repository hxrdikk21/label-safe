"""rate_limit_counters: login failures, per-IP request limits and the daily Gemini budget.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_counters",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("bucket", sa.BigInteger(), primary_key=True),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rate_limit_counters_updated_at", "rate_limit_counters", ["updated_at"])


def downgrade() -> None:
    op.drop_table("rate_limit_counters")
