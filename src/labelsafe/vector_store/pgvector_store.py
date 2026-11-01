"""
PostgreSQL + pgvector persistence for passage embeddings.

``VectorStoreClient`` keeps vectors in memory for tests and offline runs; this
store writes them to the canonical PostgreSQL database in the
``evidence_embeddings`` table with an HNSW cosine index (m=16, ef_construction=64)
and searches with the ``<=>`` cosine-distance operator. Embeddings are a derived
index: rows cascade-delete with their passage and can be rebuilt at any time.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.vector_store.embeddings import EmbeddingEngine, get_embedding_engine


class AsyncPGConnection(Protocol):
    """The subset of ``asyncpg.Connection`` / ``asyncpg.Pool`` used here."""

    async def execute(self, query: str, *args: object) -> str: ...

    async def executemany(self, command: str, args: Any) -> None: ...

    async def fetch(self, query: str, *args: object) -> list[Any]: ...


def to_pgvector(vector: Sequence[float]) -> str:
    """pgvector's text input format, e.g. ``[0.1,0.2]``."""
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


class PgVectorStore:
    def __init__(
        self,
        connection: AsyncPGConnection,
        embedding_engine: EmbeddingEngine | None = None,
        model_name: str | None = None,
    ) -> None:
        self._conn = connection
        self.embedding_engine = embedding_engine or get_embedding_engine()
        self.model_name = model_name or getattr(self.embedding_engine, "model_name", "labelsafe-hashed-v1")

    async def ensure_schema(self, *, link_to_passages: bool = True) -> None:
        """Creates the extension, table and HNSW index (idempotent).

        With ``link_to_passages`` the table references ``evidence_passages`` with
        ``ON DELETE CASCADE``; disable it for a standalone vector database.
        """
        dimension = self.embedding_engine.dimension
        reference = " REFERENCES evidence_passages(passage_id) ON DELETE CASCADE" if link_to_passages else ""
        await self._conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await self._conn.execute(
            f"""CREATE TABLE IF NOT EXISTS evidence_embeddings (
                passage_id UUID PRIMARY KEY{reference},
                embedding vector({int(dimension)}) NOT NULL,
                embedding_model VARCHAR(64) NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )"""
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_evidence_embeddings_hnsw ON evidence_embeddings "
            "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
        )

    async def upsert(self, passages: Sequence[EvidencePassage]) -> int:
        """Embeds and stores passages; re-running with the same passages is a no-op update."""
        if not passages:
            return 0
        embeddings = self.embedding_engine.embed_batch([p.content for p in passages])
        rows = [
            (p.passage_id, to_pgvector(e.vector), self.model_name)
            for p, e in zip(passages, embeddings, strict=True)
        ]
        await self._conn.executemany(
            "INSERT INTO evidence_embeddings (passage_id, embedding, embedding_model) "
            "VALUES ($1::uuid, $2::vector, $3) "
            "ON CONFLICT (passage_id) DO UPDATE SET embedding = EXCLUDED.embedding, "
            "embedding_model = EXCLUDED.embedding_model",
            rows,
        )
        return len(rows)

    async def stale_passage_ids(self) -> list[str]:
        """Passages with no embedding, or one made by a different model (e.g. after MODEL_MODE changed)."""
        rows = await self._conn.fetch(
            "SELECT p.passage_id::text AS passage_id FROM evidence_passages p "
            "LEFT JOIN evidence_embeddings e ON e.passage_id = p.passage_id "
            "WHERE e.embedding_model IS DISTINCT FROM $1",
            self.model_name,
        )
        return [r["passage_id"] for r in rows]

    async def search(self, query: str, top_k: int = 10, rxcui: str | None = None) -> list[tuple[str, float]]:
        """Nearest passages by cosine similarity, optionally restricted to one RxCUI.

        Returns ``(passage_id, similarity)`` pairs, best first; similarity is ``1 - cosine distance``.
        """
        vector = to_pgvector(self.embedding_engine.embed_text(query).vector)
        if rxcui is None:
            rows = await self._conn.fetch(
                "SELECT passage_id::text AS passage_id, 1 - (embedding <=> $1::vector) AS similarity "
                "FROM evidence_embeddings ORDER BY embedding <=> $1::vector LIMIT $2",
                vector,
                top_k,
            )
        else:
            rows = await self._conn.fetch(
                "SELECT e.passage_id::text AS passage_id, 1 - (e.embedding <=> $1::vector) AS similarity "
                "FROM evidence_embeddings e JOIN evidence_passages p ON p.passage_id = e.passage_id "
                "WHERE p.rxcui = $3 ORDER BY e.embedding <=> $1::vector LIMIT $2",
                vector,
                top_k,
                rxcui,
            )
        return [(str(r["passage_id"]), float(r["similarity"])) for r in rows]

    async def delete(self, passage_ids: Sequence[str]) -> None:
        await self._conn.execute(
            "DELETE FROM evidence_embeddings WHERE passage_id = ANY($1::uuid[])", list(passage_ids)
        )
