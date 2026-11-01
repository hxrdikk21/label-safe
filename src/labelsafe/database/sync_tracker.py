"""
``derived_sync_status`` utilities.

Canonical writers enqueue entities here inside the same transaction as the
PostgreSQL write; the pgvector embedder (``ingest_labels``) polls
for pending entities and acknowledge them. Enqueueing is idempotent: an
unchanged version is a no-op, a new version resets the entity to PENDING.
"""

import uuid
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.labelsafe.database.models import (
    DerivedSyncStatus,
    DrugProductRecord,
    EntityType,
    EvidencePassageRecord,
    MedicationConceptRecord,
    SourceDocumentRecord,
    SyncState,
    TargetStore,
)

# Only passages feed a derived store (pgvector); the Neo4j graph was removed, so nothing else is queued.
DEFAULT_TARGETS: Final[dict[EntityType, tuple[TargetStore, ...]]] = {
    EntityType.CONCEPT: (),
    EntityType.PRODUCT: (),
    EntityType.DOCUMENT: (),
    EntityType.PASSAGE: (TargetStore.PGVECTOR,),
}
DEFAULT_MAX_ATTEMPTS: Final = 5

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def enqueue_in_session(
    session: AsyncSession,
    entity_id: str,
    entity_type: EntityType,
    version: str,
    target_stores: Iterable[TargetStore] | None = None,
) -> int:
    """Marks an entity version as pending for each target store. Returns the number of rows changed."""
    changed = 0
    for store in target_stores or DEFAULT_TARGETS[entity_type]:
        row = await session.scalar(
            select(DerivedSyncStatus).where(
                DerivedSyncStatus.entity_id == entity_id, DerivedSyncStatus.target_store == store
            )
        )
        if row is None:
            session.add(
                DerivedSyncStatus(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    target_store=store,
                    sync_status=SyncState.PENDING,
                    version=version,
                    attempt_count=0,
                )
            )
            changed += 1
        elif row.version != version:
            row.version = version
            row.sync_status = SyncState.PENDING
            row.attempt_count = 0
            row.error_message = None
            changed += 1
    return changed


class SyncTracker:
    """Queue of entities whose derived pgvector embeddings need (re)building."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, clock: Clock = _utc_now) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def enqueue(
        self,
        entity_id: str,
        entity_type: EntityType,
        version: str,
        target_stores: Iterable[TargetStore] | None = None,
    ) -> int:
        async with self._session_factory() as session, session.begin():
            return await enqueue_in_session(session, entity_id, entity_type, version, target_stores)

    async def get_pending_sync_entities(
        self, target_store: str = "PGVECTOR", *, limit: int = 500, max_attempts: int = DEFAULT_MAX_ATTEMPTS
    ) -> list[dict[str, Any]]:
        """
        Returns canonical concepts, products, documents and passages awaiting ingestion by ``target_store``.

        Each item carries ``entity_id``, ``entity_type``, ``version``, ``sync_status``, ``attempt_count``
        and ``payload`` (the canonical contract as JSON, or None if the entity was deleted).
        FAILED entities are retried until ``max_attempts`` is reached.
        """
        store = TargetStore(target_store)
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(DerivedSyncStatus)
                    .where(
                        DerivedSyncStatus.target_store == store,
                        DerivedSyncStatus.sync_status.in_([SyncState.PENDING, SyncState.FAILED]),
                        DerivedSyncStatus.attempt_count < max_attempts,
                    )
                    .order_by(DerivedSyncStatus.created_at, DerivedSyncStatus.entity_id)
                    .limit(limit)
                )
            ).all()
            payloads = await self._load_payloads(session, rows)
        return [
            {
                "sync_id": str(row.sync_id),
                "entity_id": row.entity_id,
                "entity_type": row.entity_type.value,
                "target_store": row.target_store.value,
                "version": row.version,
                "sync_status": row.sync_status.value,
                "attempt_count": row.attempt_count,
                "payload": payloads.get((row.entity_type, row.entity_id)),
            }
            for row in rows
        ]

    async def mark_synced(self, entity_id: str, target_store: str = "PGVECTOR") -> None:
        """Marks entity as successfully synchronized in derived_sync_status."""
        await self._transition(entity_id, target_store, SyncState.SYNCED, None)

    async def mark_failed(self, entity_id: str, target_store: str, error: str) -> None:
        """Records a failed sync attempt; the entity is retried until max_attempts."""
        await self._transition(entity_id, target_store, SyncState.FAILED, error[:2000])

    async def _transition(
        self, entity_id: str, target_store: str, state: SyncState, error: str | None
    ) -> None:
        store = TargetStore(target_store)
        async with self._session_factory() as session, session.begin():
            row = await session.scalar(
                select(DerivedSyncStatus).where(
                    DerivedSyncStatus.entity_id == entity_id, DerivedSyncStatus.target_store == store
                )
            )
            if row is None:
                raise LookupError(f"no sync entry for {entity_id} in {store.value}")
            row.sync_status = state
            row.error_message = error
            row.attempt_count += 1
            row.last_attempt = self._clock()

    @staticmethod
    async def _load_payloads(
        session: AsyncSession, rows: Sequence[DerivedSyncStatus]
    ) -> dict[tuple[EntityType, str], dict[str, Any]]:
        ids: dict[EntityType, list[str]] = {}
        for row in rows:
            ids.setdefault(row.entity_type, []).append(row.entity_id)
        payloads: dict[tuple[EntityType, str], dict[str, Any]] = {}
        if concept_ids := ids.get(EntityType.CONCEPT):
            for c in await session.scalars(
                select(MedicationConceptRecord).where(MedicationConceptRecord.rxcui.in_(concept_ids))
            ):
                payloads[(EntityType.CONCEPT, c.rxcui)] = c.to_contract().model_dump(mode="json")
        if product_ids := ids.get(EntityType.PRODUCT):
            for p in await session.scalars(
                select(DrugProductRecord).where(DrugProductRecord.ndc.in_(product_ids))
            ):
                payloads[(EntityType.PRODUCT, p.ndc)] = p.to_contract().model_dump(mode="json")
        if document_ids := ids.get(EntityType.DOCUMENT):
            for d in await session.scalars(
                select(SourceDocumentRecord).where(SourceDocumentRecord.document_id.in_(document_ids))
            ):
                payloads[(EntityType.DOCUMENT, d.document_id)] = d.to_contract().model_dump(mode="json")
        if passage_ids := ids.get(EntityType.PASSAGE):
            for e in await session.scalars(
                select(EvidencePassageRecord).where(
                    EvidencePassageRecord.passage_id.in_([uuid.UUID(i) for i in passage_ids])
                )
            ):
                payloads[(EntityType.PASSAGE, str(e.passage_id))] = e.to_contract().model_dump(mode="json")
        return payloads
