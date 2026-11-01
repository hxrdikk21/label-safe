"""
Label ingestion: FDA label text into PostgreSQL, then embeddings into pgvector.

    python -m src.labelsafe.ingestion.ingest_labels --limit 10
    python -m src.labelsafe.ingestion.ingest_labels --rxcui 11289 5640

For each catalogue drug (seed it first with ``seed_loader``): fetch the newest DailyMed SPL by
RxCUI, falling back to openFDA by generic name, and save it with ``LabelRepository`` (idempotent).
Every new or changed passage is queued for PGVECTOR; ``embed_pending`` drains that queue.
"""

import argparse
import asyncio
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import httpx
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.core.contracts.medication import MedicationConcept
from src.labelsafe.database.passage_repository import LabelRepository, PassageRepository
from src.labelsafe.database.sync_tracker import SyncTracker
from src.labelsafe.ingestion.dailymed import DailyMedClient
from src.labelsafe.ingestion.errors import UpstreamNotFoundError, UpstreamUnavailableError
from src.labelsafe.ingestion.openfda import LabelDeduplicator, OpenFDAClient

if TYPE_CHECKING:
    from src.labelsafe.vector_store.pgvector_store import PgVectorStore

logger = logging.getLogger(__name__)


class VectorSink(Protocol):
    async def upsert(self, passages: Sequence[EvidencePassage]) -> int: ...


_UNWANTED_LABEL = re.compile(r"homeopathic|\bkit\b|veterinary|\banimal", re.IGNORECASE)


def pick_label(hits: Sequence[Any], drug: str) -> Any:
    """The best DailyMed hit for a drug: not homeopathic, a kit or veterinary; naming the drug; and
    the shortest title (multi-ingredient remedies list every ingredient and have long titles).
    DailyMed's first hit for an ingredient can be such a product (lithium returned a homeopathic mix)."""

    def rank(hit: Any) -> tuple[bool, bool, int]:
        title = str(getattr(hit, "title", "") or "")
        return bool(_UNWANTED_LABEL.search(title)), drug.lower() not in title.lower(), len(title)

    return min(hits, key=rank)


@dataclass
class IngestReport:
    labels_saved: int = 0
    passages_written: int = 0
    not_found: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


async def ingest_labels(
    session_factory: async_sessionmaker[AsyncSession],
    concepts: Sequence[MedicationConcept],
    dailymed: DailyMedClient,
    openfda: OpenFDAClient,
) -> IngestReport:
    repository = LabelRepository(session_factory)
    report = IngestReport()
    for concept in concepts:
        try:
            try:
                hits = await dailymed.search_spls(rxcui=concept.rxcui, page_size=10)
                hit = pick_label(hits, concept.canonical_name)
                labels = [await dailymed.fetch_label(hit.setid, rxcui=concept.rxcui)]
            except UpstreamNotFoundError:
                labels = await openfda.fetch_labels_for_generic(  # type: ignore[assignment]
                    concept.canonical_name, rxcui=concept.rxcui, deduplicator=LabelDeduplicator(), limit=1
                )
            for label in labels:
                written = await repository.save_label(
                    label.document,
                    label.passages,
                    label.products,
                    missing_excipient_data=label.missing_excipient_data,
                )
                report.labels_saved += 1
                report.passages_written += written.passages_written
        except UpstreamNotFoundError:
            report.not_found.append(concept.rxcui)
        except (UpstreamUnavailableError, httpx.HTTPError, ValueError, DBAPIError) as exc:
            # One bad label must not stop the batch; it is reported and can be retried.
            logger.warning("Ingest failed for %s (%s): %s", concept.canonical_name, concept.rxcui, exc)
            report.failed.append(concept.rxcui)
    return report


async def embed_pending(
    session_factory: async_sessionmaker[AsyncSession], sink: VectorSink, batch_size: int = 64
) -> int:
    """Embeds queued passages into pgvector until the PGVECTOR queue is empty. Returns passages embedded."""
    tracker = SyncTracker(session_factory)
    embedded = 0
    while pending := await tracker.get_pending_sync_entities("PGVECTOR", limit=batch_size):
        passages = [EvidencePassage.model_validate(row["payload"]) for row in pending if row["payload"]]
        try:
            embedded += await sink.upsert(passages)
        except Exception as exc:
            # Record the failure on each row and stop; the rows are retried on the next run.
            for row in pending:
                await tracker.mark_failed(row["entity_id"], "PGVECTOR", str(exc))
            raise
        # Rows whose passage was deleted (payload None) are done too: there is nothing left to embed.
        for row in pending:
            await tracker.mark_synced(row["entity_id"], "PGVECTOR")
    return embedded


async def embed_stale(
    session_factory: async_sessionmaker[AsyncSession], store: "PgVectorStore", batch_size: int = 64
) -> int:
    """Re-embeds passages whose vector is missing or came from another model, so one index never mixes
    vector spaces. Returns passages embedded."""
    ids = await store.stale_passage_ids()
    repo = PassageRepository(session_factory)
    embedded = 0
    for start in range(0, len(ids), batch_size):
        batch = [p for pid in ids[start : start + batch_size] if (p := await repo.get_passage(pid))]
        embedded += await store.upsert(batch)
    return embedded


async def _main(argv: list[str] | None = None) -> None:  # pragma: no cover - thin CLI wrapper
    import asyncpg
    from sqlalchemy import make_url

    from src.labelsafe.core.config import get_settings
    from src.labelsafe.database.connection import create_engine, create_session_factory
    from src.labelsafe.ingestion.seed_loader import load_catalog
    from src.labelsafe.vector_store.pgvector_store import PgVectorStore

    parser = argparse.ArgumentParser(description="Fetch FDA labels into PostgreSQL and embed them.")
    parser.add_argument("--limit", type=int, default=10, help="First N catalogue drugs by priority")
    parser.add_argument("--rxcui", nargs="*", default=None, help="Only these RxCUIs")
    args = parser.parse_args(argv)

    settings = get_settings()
    catalog = sorted(load_catalog().concepts, key=lambda c: c.priority_rank)
    concepts = [c.concept for c in catalog if args.rxcui is None or c.concept.rxcui in args.rxcui]
    if args.rxcui is None:
        concepts = concepts[: args.limit]

    engine = create_engine(settings.database_url)
    # Plain asyncpg wants a libpq DSN: no +asyncpg driver, and sslmode= rather than SQLAlchemy's ssl=.
    dsn = make_url(settings.database_url).set(drivername="postgresql")
    if isinstance(ssl := dsn.query.get("ssl"), str):
        dsn = dsn.update_query_dict({"sslmode": ssl}).difference_update_query(["ssl"])
    connection = await asyncpg.connect(dsn.render_as_string(hide_password=False))
    try:
        factory = create_session_factory(engine)
        async with httpx.AsyncClient(timeout=30) as http:
            report = await ingest_labels(
                factory,
                concepts,
                DailyMedClient(http, base_url=settings.dailymed_base_url),
                OpenFDAClient(http, api_key=settings.openfda_api_key),
            )
        print(report)
        store = PgVectorStore(connection)
        await store.ensure_schema()
        print(f"embedded {await embed_pending(factory, store)} passages with {store.model_name}")
        print(f"re-embedded {await embed_stale(factory, store)} older passages with {store.model_name}")
    finally:
        await connection.close()
        await engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
