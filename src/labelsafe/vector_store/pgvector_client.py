"""
pgvector-compatible Vector Store Client.
Provides HNSW parameterization (m=16, ef_construction=64) and Cosine Distance similarity search
over canonical EvidencePassage chunks.
Operates seamlessly in-memory for testing, with direct drop-in SQL generation for PostgreSQL 16 + pgvector.
"""

from pydantic import BaseModel, Field

from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.vector_store.embeddings import EmbeddingEngine, get_embedding_engine


class ScoredPassage(BaseModel):
    passage: EvidencePassage
    score: float = Field(..., ge=-1.0, le=1.0, description="Cosine similarity score")
    rank: int = Field(..., ge=1)


class VectorStoreClient:
    """
    High-performance vector index client supporting dense nearest-neighbor search.
    Implements HNSW indexing parameters and cosine distance retrieval.
    """

    def __init__(
        self,
        embedding_engine: EmbeddingEngine | None = None,
        m: int = 16,
        ef_construction: int = 64,
    ):
        self.embedding_engine = embedding_engine or get_embedding_engine()
        self.m = m
        self.ef_construction = ef_construction
        # Primary storage: passage_id -> (EvidencePassage, List[float])
        self._index: dict[str, tuple[EvidencePassage, list[float]]] = {}

    def insert_passage(self, passage: EvidencePassage) -> None:
        """Embeds and indexes a single EvidencePassage."""
        emb = self.embedding_engine.embed_text(passage.content)
        # Mark embedding_status as INDEXED
        passage_indexed = passage.model_copy(update={"embedding_status": "INDEXED"})
        self._index[passage.passage_id] = (passage_indexed, emb.vector)

    def insert_batch(self, passages: list[EvidencePassage]) -> int:
        """Batch indexes multiple EvidencePassage objects."""
        for p in passages:
            self.insert_passage(p)
        return len(passages)

    def search_similar(
        self,
        query: str,
        top_k: int = 5,
        filter_rxcui: str | None = None,
        filter_loinc_code: str | None = None,
    ) -> list[ScoredPassage]:
        """
        Executes nearest neighbor similarity search against indexed passages.
        Optionally pre-filters by RxCUI and LOINC section code.
        """
        if not self._index or not query.strip():
            return []

        query_emb = self.embedding_engine.embed_text(query)
        candidates: list[tuple[EvidencePassage, float]] = []

        for _passage_id, (passage, vector) in self._index.items():
            # Apply metadata filters
            if filter_rxcui and passage.rxcui != filter_rxcui:
                continue
            if filter_loinc_code and passage.loinc_section_code != filter_loinc_code:
                continue

            similarity = self.embedding_engine.cosine_similarity(query_emb.vector, vector)
            candidates.append((passage, similarity))

        # Sort descending by similarity score
        candidates.sort(key=lambda item: item[1], reverse=True)

        results: list[ScoredPassage] = []
        for rank, (passage, score) in enumerate(candidates[:top_k], start=1):
            results.append(
                ScoredPassage(
                    passage=passage,
                    score=round(score, 4),
                    rank=rank,
                )
            )

        return results

    def clear(self) -> None:
        """Clears all vectors in index."""
        self._index.clear()

    def count(self) -> int:
        """Returns number of indexed passages."""
        return len(self._index)

    def generate_pgvector_ddl(self) -> str:
        """Generates exact PostgreSQL DDL for pgvector extension and HNSW index."""
        return f"""-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Canonical evidence embeddings table
CREATE TABLE IF NOT EXISTS evidence_embeddings (
    passage_id VARCHAR(64) PRIMARY KEY,
    document_id VARCHAR(128) NOT NULL,
    rxcui VARCHAR(32) NOT NULL,
    loinc_section_code VARCHAR(32) NOT NULL,
    embedding vector({self.embedding_engine.dimension}),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- HNSW cosine distance index
CREATE INDEX IF NOT EXISTS idx_evidence_embeddings_hnsw
ON evidence_embeddings
USING hnsw (embedding vector_cosine_ops)
WITH (m = {self.m}, ef_construction = {self.ef_construction});
"""
