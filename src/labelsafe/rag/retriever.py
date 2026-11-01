"""
Step 1-2 of the RAG pipeline: rxcui-scoped hybrid retrieval fused with Reciprocal Rank Fusion.

``PostgresRetriever`` runs pgvector cosine search and ``tsvector`` keyword search against the
canonical database; ``InMemoryRetriever`` is the same pipeline over a passage list (tests, offline).
"""

import asyncio
import logging
import re
import uuid
from collections import defaultdict
from collections.abc import Sequence
from typing import Any, Protocol

from sqlalchemy import TextClause, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.database.models import EvidencePassageRecord
from src.labelsafe.vector_store.embeddings import EmbeddingEngine, get_embedding_engine
from src.labelsafe.vector_store.pgvector_client import VectorStoreClient
from src.labelsafe.vector_store.pgvector_store import to_pgvector

logger = logging.getLogger(__name__)

_TERM = re.compile(r"[a-z0-9]{3,}")


def rrf(rankings: Sequence[Sequence[EvidencePassage]], k: int = 60) -> list[EvidencePassage]:
    """Reciprocal Rank Fusion: score(d) = sum over rankings of 1 / (k + rank(d)), best first."""
    scores: dict[str, float] = defaultdict(float)
    by_id: dict[str, EvidencePassage] = {}
    for ranking in rankings:
        for rank, passage in enumerate(ranking, start=1):
            by_id[passage.passage_id] = passage
            scores[passage.passage_id] += 1.0 / (k + rank)
    return [by_id[pid] for pid in sorted(scores, key=lambda pid: scores[pid], reverse=True)]


def query_terms(query: str) -> list[str]:
    return list(dict.fromkeys(_TERM.findall(query.lower())))


class Retriever(Protocol):
    async def search(self, query: str, rxcuis: Sequence[str], top_k: int) -> list[EvidencePassage]: ...


class InMemoryRetriever:
    """Dense (``VectorStoreClient``) + term-overlap keyword ranking over an in-process passage list."""

    def __init__(
        self, passages: Sequence[EvidencePassage] = (), embedding_engine: EmbeddingEngine | None = None
    ) -> None:
        self.passages = list(passages)
        # No corpus, no embedding model to load.
        self._vectors = VectorStoreClient(embedding_engine=embedding_engine) if self.passages else None
        if self._vectors:
            self._vectors.insert_batch(self.passages)

    async def search(self, query: str, rxcuis: Sequence[str], top_k: int) -> list[EvidencePassage]:
        if not query.strip() or self._vectors is None:
            return []
        scope = set(rxcuis)
        dense = [
            s.passage
            for s in self._vectors.search_similar(query, top_k=len(self.passages))
            if not scope or s.passage.rxcui in scope
        ][:top_k]
        terms = set(query_terms(query))
        overlap = {
            p.passage_id: len(terms & set(_TERM.findall(p.content.lower())))
            for p in self.passages
            if not scope or p.rxcui in scope
        }
        keyword = sorted(
            (p for p in self.passages if overlap.get(p.passage_id)),
            key=lambda p: overlap[p.passage_id],
            reverse=True,
        )[:top_k]
        return rrf([dense, keyword])[:top_k]


class PostgresRetriever:
    """pgvector + ``tsvector`` retrieval over ``evidence_passages``, filtered by rxcui."""

    # Served by the GIN index on to_tsvector('english', content) (migration 0003).
    _KEYWORD_SQL = text(
        "SELECT passage_id::text AS passage_id FROM evidence_passages "
        "WHERE rxcui = ANY(:rxcuis) AND to_tsvector('english', content) @@ to_tsquery('english', :terms) "
        "ORDER BY ts_rank_cd(to_tsvector('english', content), to_tsquery('english', :terms)) DESC "
        "LIMIT :k"
    )
    _VECTOR_SQL = text(
        "SELECT e.passage_id::text AS passage_id FROM evidence_embeddings e "
        "JOIN evidence_passages p ON p.passage_id = e.passage_id "
        "WHERE p.rxcui = ANY(:rxcuis) ORDER BY e.embedding <=> CAST(:vec AS vector) LIMIT :k"
    )

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_engine: EmbeddingEngine | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_engine = embedding_engine

    async def _ids(self, statement: TextClause, params: dict[str, Any]) -> list[str]:
        try:
            async with self._session_factory() as session:
                rows = await session.execute(statement, params)
                return [str(r.passage_id) for r in rows]
        except DBAPIError as exc:
            # Embeddings are a derived index that may not be built yet; keyword search still answers.
            logger.warning("Retrieval query failed; continuing without it: %s", exc)
            return []

    async def search(self, query: str, rxcuis: Sequence[str], top_k: int) -> list[EvidencePassage]:
        terms = query_terms(query)
        if not terms or not rxcuis:
            return []
        engine = self._embedding_engine or get_embedding_engine()
        scope = list(rxcuis)
        embedding = await asyncio.to_thread(engine.embed_text, query)  # model inference: off the event loop
        vector = to_pgvector(embedding.vector)
        dense_ids = await self._ids(self._VECTOR_SQL, {"rxcuis": scope, "vec": vector, "k": top_k})
        keyword_ids = await self._ids(
            self._KEYWORD_SQL, {"rxcuis": scope, "terms": " | ".join(terms), "k": top_k}
        )
        wanted = {uuid.UUID(pid) for pid in dense_ids + keyword_ids}
        if not wanted:
            return []
        async with self._session_factory() as session:
            records = await session.scalars(
                select(EvidencePassageRecord).where(EvidencePassageRecord.passage_id.in_(wanted))
            )
            by_id = {str(r.passage_id): r.to_contract() for r in records}
        rankings = [[by_id[pid] for pid in ids if pid in by_id] for ids in (dense_ids, keyword_ids)]
        return rrf(rankings)[:top_k]
