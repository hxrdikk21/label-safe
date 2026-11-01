"""
PgVectorStore against PostgreSQL 16 + pgvector, on Mudit's canonical schema
(src/rxguard/database). Skipped automatically when Docker is unavailable.
"""

import hashlib
import uuid
import warnings
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
import pytest_asyncio

from src.rxguard.core.contracts.evidence import EvidencePassage
from src.rxguard.database import models
from src.rxguard.database.connection import create_all, create_engine
from src.rxguard.vector_store.embeddings import EmbeddingEngine
from src.rxguard.vector_store.pgvector_store import PgVectorStore


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(not _docker_available(), reason="Docker daemon not available")

TEXTS = {
    "warfarin": "Concomitant warfarin and amiodarone markedly increases INR and bleeding risk.",
    "metformin": "Metformin is contraindicated in severe renal impairment due to lactic acidosis.",
    "ibuprofen": "Ibuprofen is contraindicated in active peptic ulcer disease.",
}
RXCUIS = {"warfarin": "11289", "metformin": "6809", "ibuprofen": "5640"}


@pytest.fixture(scope="module")
def pgvector_url() -> Iterator[str]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver=None) as container:
        yield container.get_connection_url()


def passage(name: str) -> EvidencePassage:
    return EvidencePassage(
        passage_id=str(uuid.uuid5(uuid.NAMESPACE_URL, name)),
        document_id=f"SPL-{name}",
        rxcui=RXCUIS[name],
        loinc_section_code="34073-7",
        section_title="Drug Interactions",
        passage_index=0,
        content=TEXTS[name],
        sha256_hash=hashlib.sha256(TEXTS[name].encode()).hexdigest(),
    )


@pytest_asyncio.fixture
async def store(pgvector_url: str) -> AsyncIterator[tuple[PgVectorStore, asyncpg.Connection]]:
    engine = create_engine(pgvector_url.replace("postgresql://", "postgresql+asyncpg://", 1))
    async with engine.begin() as conn:
        await conn.exec_driver_sql("DROP TABLE IF EXISTS evidence_embeddings")
        await conn.run_sync(models.Base.metadata.drop_all)
    await create_all(engine)
    async with engine.begin() as conn:
        for name in TEXTS:
            p = passage(name)
            await conn.execute(
                models.MedicationConceptRecord.__table__.insert().values(
                    rxcui=p.rxcui,
                    canonical_name=name,
                    term_type="IN",
                    ingredients=[],
                    synonyms=[],
                    ambiguity_candidates=[],
                    content_hash="0" * 64,
                )
            )
            await conn.execute(
                models.SourceDocumentRecord.__table__.insert().values(
                    document_id=p.document_id,
                    source_name="DailyMed",
                    source_url="https://x",
                    version="1",
                    title=name,
                    sha256_hash="0" * 64,
                )
            )
            await conn.execute(
                models.EvidencePassageRecord.__table__.insert().values(
                    passage_id=uuid.UUID(p.passage_id),
                    document_id=p.document_id,
                    rxcui=p.rxcui,
                    loinc_section_code=p.loinc_section_code,
                    section_title=p.section_title,
                    passage_index=0,
                    content=p.content,
                    sha256_hash=p.sha256_hash,
                    chunk_version="1.0.0",
                )
            )
    await engine.dispose()
    conn = await asyncpg.connect(pgvector_url)
    try:
        yield PgVectorStore(conn, embedding_engine=EmbeddingEngine(dimension=384)), conn
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_schema_upsert_and_cosine_search(store: tuple[PgVectorStore, asyncpg.Connection]) -> None:
    vectors, conn = store
    await vectors.ensure_schema()
    await vectors.ensure_schema()  # idempotent
    index = await conn.fetchval(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_evidence_embeddings_hnsw'"
    )
    assert "hnsw" in index and "vector_cosine_ops" in index and "m='16'" in index

    passages = [passage(n) for n in TEXTS]
    assert await vectors.upsert(passages) == 3
    assert await vectors.upsert(passages) == 3  # re-run updates in place
    assert await conn.fetchval("SELECT count(*) FROM evidence_embeddings") == 3

    hits = await vectors.search("warfarin amiodarone INR bleeding", top_k=3)
    assert hits[0][0] == passage("warfarin").passage_id
    assert hits[0][1] >= hits[-1][1]
    only_metformin = await vectors.search("contraindicated", top_k=5, rxcui="6809")
    assert [pid for pid, _ in only_metformin] == [passage("metformin").passage_id]


@pytest.mark.asyncio
async def test_embeddings_cascade_with_passages(store: tuple[PgVectorStore, asyncpg.Connection]) -> None:
    vectors, conn = store
    await vectors.ensure_schema()
    await vectors.upsert([passage(n) for n in TEXTS])
    await conn.execute("DELETE FROM evidence_passages WHERE rxcui = '5640'")
    assert await conn.fetchval("SELECT count(*) FROM evidence_embeddings") == 2
    await vectors.delete([passage("warfarin").passage_id])
    assert await conn.fetchval("SELECT count(*) FROM evidence_embeddings") == 1
