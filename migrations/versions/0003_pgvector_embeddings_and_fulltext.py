"""pgvector embeddings table and full-text index for hybrid retrieval.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None

# Must match the embedding model's dimension (BAAI/bge-small-en-v1.5 = 384, core/config.py).
EMBEDDING_DIMENSION = 384


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        f"""CREATE TABLE IF NOT EXISTS evidence_embeddings (
            passage_id UUID PRIMARY KEY REFERENCES evidence_passages(passage_id) ON DELETE CASCADE,
            embedding vector({EMBEDDING_DIMENSION}) NOT NULL,
            embedding_model VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_evidence_embeddings_hnsw ON evidence_embeddings "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    # Same expression as PostgresRetriever's keyword query, so the planner can use it.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_evidence_passages_fts ON evidence_passages "
        "USING gin (to_tsvector('english', content))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_evidence_passages_fts")
    op.execute("DROP TABLE IF EXISTS evidence_embeddings")
