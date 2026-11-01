"""
Seeder for the 500 high-priority medication concepts.

The catalog in ``data/seed/top_500_concepts.json`` is resolved ahead of time
against RxNav (see ``scripts/build_seed_catalog.py``), so seeding is fully
offline and deterministic. Every concept row carries a SHA-256 content hash:
re-running the seeder against an up-to-date database writes nothing.

Usage::

    python -m src.rxguard.ingestion.seed_loader --database-url postgresql+asyncpg://... [--create-tables]
"""

import argparse
import asyncio
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.rxguard.core.contracts.medication import MedicationConcept
from src.rxguard.database.models import EntityType, MedicationConceptRecord
from src.rxguard.database.sync_tracker import enqueue_in_session
from src.rxguard.ingestion.cache_manager import CacheManager
from src.rxguard.ingestion.errors import SourceAdapterError
from src.rxguard.ingestion.hashing import fingerprint_json
from src.rxguard.knowledge.normalizer import CACHE_SOURCE, MedicationNormalizer

logger = logging.getLogger(__name__)

DEFAULT_CATALOG_PATH: Final = Path(__file__).resolve().parents[3] / "data" / "seed" / "top_500_concepts.json"
EXPECTED_CONCEPT_COUNT: Final = 500
DEFAULT_BATCH_SIZE: Final = 100


class SeedConcept(BaseModel):
    """One catalog entry: a canonical concept plus curation metadata."""

    model_config = ConfigDict(extra="forbid")

    priority_rank: int = Field(..., ge=1)
    therapeutic_category: str = Field(..., min_length=1)
    is_narrow_therapeutic_index: bool = False
    concept: MedicationConcept

    def content_hash(self) -> str:
        return fingerprint_json(self.model_dump(mode="json"))


class SeedCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_version: str
    generated_from: str
    concepts: list[SeedConcept]

    def catalog_hash(self) -> str:
        return fingerprint_json([c.content_hash() for c in self.concepts])


@dataclass(frozen=True, slots=True)
class SeedReport:
    total: int
    inserted: int
    updated: int
    unchanged: int
    catalog_hash: str


class CatalogValidationError(ValueError):
    """The seed catalog is structurally invalid."""


def load_catalog(
    path: Path = DEFAULT_CATALOG_PATH, *, expected_count: int | None = EXPECTED_CONCEPT_COUNT
) -> SeedCatalog:
    """Loads and validates the seed catalog (contract conformance, uniqueness and size)."""
    catalog = SeedCatalog.model_validate(json.loads(path.read_text(encoding="utf-8")))
    validate_catalog(catalog, expected_count=expected_count)
    return catalog


def validate_catalog(catalog: SeedCatalog, *, expected_count: int | None = EXPECTED_CONCEPT_COUNT) -> None:
    rxcuis = [c.concept.rxcui for c in catalog.concepts]
    ranks = [c.priority_rank for c in catalog.concepts]
    if len(set(rxcuis)) != len(rxcuis):
        raise CatalogValidationError("duplicate RxCUIs in seed catalog")
    if sorted(ranks) != list(range(1, len(ranks) + 1)):
        raise CatalogValidationError("priority ranks must be unique and contiguous from 1")
    if expected_count is not None and len(catalog.concepts) != expected_count:
        raise CatalogValidationError(f"expected {expected_count} concepts, found {len(catalog.concepts)}")


def _record_values(entry: SeedConcept, content_hash: str) -> dict[str, Any]:
    concept = entry.concept
    return {
        "rxcui": concept.rxcui,
        "canonical_name": concept.canonical_name,
        "term_type": concept.term_type,
        "ingredients": [i.model_dump(mode="json") for i in concept.ingredients],
        "synonyms": list(concept.synonyms),
        "jurisdiction": concept.jurisdiction,
        "is_ambiguous": concept.is_ambiguous,
        "ambiguity_candidates": list(concept.ambiguity_candidates),
        "priority_rank": entry.priority_rank,
        "therapeutic_category": entry.therapeutic_category,
        "is_narrow_therapeutic_index": entry.is_narrow_therapeutic_index,
        "content_hash": content_hash,
    }


class SeedLoader:
    """Idempotent batch loader for :class:`SeedCatalog` into ``medication_concepts``."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        cache: CacheManager | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._session_factory = session_factory
        self._cache = cache
        self._batch_size = batch_size

    async def seed(self, catalog: SeedCatalog) -> SeedReport:
        inserted = updated = unchanged = 0
        entries = catalog.concepts
        for start in range(0, len(entries), self._batch_size):
            batch = entries[start : start + self._batch_size]
            async with self._session_factory() as session, session.begin():
                for entry in batch:
                    content_hash = entry.content_hash()
                    values = _record_values(entry, content_hash)
                    record = await session.get(MedicationConceptRecord, entry.concept.rxcui)
                    if record is None:
                        session.add(MedicationConceptRecord(**values))
                        inserted += 1
                    elif record.content_hash != content_hash:
                        for column, value in values.items():
                            setattr(record, column, value)
                        updated += 1
                    else:
                        unchanged += 1
                        continue
                    await enqueue_in_session(session, entry.concept.rxcui, EntityType.CONCEPT, content_hash)
            if self._cache is not None:
                for entry in batch:
                    # Pre-warm the normalizer cache so seeded canonical names resolve with zero HTTP calls.
                    await self._cache.put(
                        CACHE_SOURCE,
                        f"{entry.concept.jurisdiction}:{entry.concept.canonical_name}",
                        entry.concept.model_dump(mode="json"),
                    )
        report = SeedReport(len(entries), inserted, updated, unchanged, catalog.catalog_hash())
        logger.info("Seed complete: %s", report)
        return report


@dataclass(frozen=True, slots=True)
class CuratedMedication:
    """A curated input name for catalog generation."""

    name: str
    therapeutic_category: str
    is_narrow_therapeutic_index: bool = False


async def build_catalog(
    curated: Iterable[CuratedMedication],
    normalizer: MedicationNormalizer,
    *,
    target_count: int = EXPECTED_CONCEPT_COUNT,
    catalog_version: str,
    generated_from: str = "NIH NLM RxNav REST API",
) -> tuple[SeedCatalog, list[str]]:
    """
    Resolves curated names through the normalizer, skipping unresolvable names and
    duplicate RxCUIs, until ``target_count`` concepts are collected.
    Returns the catalog and the list of skipped names with reasons.
    """
    concepts: list[SeedConcept] = []
    seen: set[str] = set()
    skipped: list[str] = []
    for item in curated:
        if len(concepts) >= target_count:
            break
        try:
            concept = await normalizer.normalize(item.name)
        except SourceAdapterError as exc:
            skipped.append(f"{item.name}: {exc}")
            continue
        if concept.rxcui in seen:
            skipped.append(f"{item.name}: duplicate of RxCUI {concept.rxcui}")
            continue
        seen.add(concept.rxcui)
        concepts.append(
            SeedConcept(
                priority_rank=len(concepts) + 1,
                therapeutic_category=item.therapeutic_category,
                is_narrow_therapeutic_index=item.is_narrow_therapeutic_index,
                concept=concept,
            )
        )
    catalog = SeedCatalog(catalog_version=catalog_version, generated_from=generated_from, concepts=concepts)
    validate_catalog(catalog, expected_count=target_count)
    return catalog, skipped


async def _main(argv: list[str] | None = None) -> None:  # pragma: no cover - thin CLI wrapper
    from src.rxguard.database.connection import create_all, create_engine, create_session_factory

    parser = argparse.ArgumentParser(description="Seed the 500 high-priority medication concepts.")
    parser.add_argument("--database-url", default=None, help="Defaults to Settings.database_url")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--create-tables", action="store_true", help="Create tables (development only)")
    args = parser.parse_args(argv)

    if args.database_url is None:
        from src.rxguard.core.config import get_settings

        args.database_url = get_settings().database_url
    engine = create_engine(args.database_url)
    try:
        if args.create_tables:
            await create_all(engine)
        session_factory = create_session_factory(engine)
        report = await SeedLoader(session_factory, cache=CacheManager(session_factory)).seed(
            load_catalog(args.catalog)
        )
        print(report)
    finally:
        await engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
