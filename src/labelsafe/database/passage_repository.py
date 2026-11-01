"""
Canonical label persistence and passage read access.

``LabelRepository`` writes parsed labels (documents, passages, products) and
enqueues derived-store sync in the same transaction. ``PassageRepository`` is
the read interface consumed by the vector and lexical retrieval layer.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.labelsafe.core.contracts.document import SourceDocument
from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.core.contracts.product import DrugProduct
from src.labelsafe.database.models import (
    DrugProductRecord,
    EntityType,
    EvidencePassageRecord,
    SourceDocumentRecord,
)
from src.labelsafe.database.sync_tracker import enqueue_in_session
from src.labelsafe.ingestion.hashing import fingerprint_json


@dataclass(frozen=True, slots=True)
class LabelWriteResult:
    document_changed: bool
    passages_written: int
    products_written: int


class LabelRepository:
    """Idempotent writer for regulatory labels; unchanged content produces no writes."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save_label(
        self,
        document: SourceDocument,
        passages: list[EvidencePassage],
        products: list[DrugProduct],
        *,
        missing_excipient_data: bool,
    ) -> LabelWriteResult:
        async with self._session_factory() as session, session.begin():
            existing = await session.get(SourceDocumentRecord, document.document_id)
            document_changed = existing is None or existing.sha256_hash != document.sha256_hash
            if document_changed:
                await session.merge(
                    SourceDocumentRecord.from_contract(
                        document, missing_excipient_data=missing_excipient_data
                    )
                )
                await enqueue_in_session(
                    session, document.document_id, EntityType.DOCUMENT, document.sha256_hash
                )

            # One label per drug: when DailyMed's label for a drug moves to another document, the old
            # document's passages would otherwise stay searchable beside the new ones.
            if document.rxcui_primary:
                stale = list(
                    await session.scalars(
                        select(SourceDocumentRecord.document_id).where(
                            SourceDocumentRecord.rxcui_primary == document.rxcui_primary,
                            SourceDocumentRecord.document_id != document.document_id,
                        )
                    )
                )
                if stale:
                    await session.execute(
                        delete(EvidencePassageRecord).where(EvidencePassageRecord.document_id.in_(stale))
                    )
                    await session.execute(
                        delete(SourceDocumentRecord).where(SourceDocumentRecord.document_id.in_(stale))
                    )

            # Drop passages this document no longer has (a new label version or chunk format).
            # Their old rows would otherwise be retrieved as stale text, or collide on the
            # (document, section, index, chunk_version) key when a new version is saved.
            await session.execute(
                delete(EvidencePassageRecord).where(
                    EvidencePassageRecord.document_id == document.document_id,
                    EvidencePassageRecord.passage_id.not_in([uuid.UUID(p.passage_id) for p in passages]),
                )
            )

            passages_written = 0
            for passage in passages:
                current = await session.get(EvidencePassageRecord, uuid.UUID(passage.passage_id))
                if current is not None and current.sha256_hash == passage.sha256_hash:
                    continue
                await session.merge(EvidencePassageRecord.from_contract(passage))
                await enqueue_in_session(session, passage.passage_id, EntityType.PASSAGE, passage.sha256_hash)
                passages_written += 1

            products_written = 0
            for product in products:
                version = fingerprint_json(product.model_dump(mode="json"))
                current_product = await session.get(DrugProductRecord, product.ndc)
                if current_product is not None and current_product.to_contract() == product:
                    continue
                await session.merge(DrugProductRecord.from_contract(product))
                await enqueue_in_session(session, product.ndc, EntityType.PRODUCT, version)
                products_written += 1
        return LabelWriteResult(document_changed, passages_written, products_written)


class PassageRepository:
    """Read access to canonical evidence passages for vectorization and lexical filtering."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_passages_by_rxcui(
        self, rxcui: str, loinc_section: str | None = None
    ) -> list[EvidencePassage]:
        """Fetches canonical raw text passages for vectorization or lexical filtering."""
        query = select(EvidencePassageRecord).where(EvidencePassageRecord.rxcui == rxcui)
        if loinc_section is not None:
            query = query.where(EvidencePassageRecord.loinc_section_code == loinc_section)
        query = query.order_by(
            EvidencePassageRecord.document_id,
            EvidencePassageRecord.loinc_section_code,
            EvidencePassageRecord.passage_index,
        )
        async with self._session_factory() as session:
            return [record.to_contract() for record in await session.scalars(query)]

    async def get_passage(self, passage_id: str) -> EvidencePassage | None:
        async with self._session_factory() as session:
            record = await session.get(EvidencePassageRecord, uuid.UUID(passage_id))
            return record.to_contract() if record is not None else None

    async def get_passages(self, passage_ids: list[str]) -> list[EvidencePassage]:
        """Several passages in one query (one round trip, which matters for a remote database);
        ids that no longer exist are skipped."""
        if not passage_ids:
            return []
        query = select(EvidencePassageRecord).where(
            EvidencePassageRecord.passage_id.in_([uuid.UUID(pid) for pid in passage_ids])
        )
        async with self._session_factory() as session:
            return [record.to_contract() for record in await session.scalars(query)]
