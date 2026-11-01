"""Seeder idempotency, catalog validation, derived sync tracking and label/passage repository tests."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.labelsafe.core.contracts.medication import IngredientReference, MedicationConcept
from src.labelsafe.database.models import (
    DerivedSyncStatus,
    EntityType,
    MedicationConceptRecord,
    SyncState,
    TargetStore,
)
from src.labelsafe.database.passage_repository import LabelRepository, PassageRepository
from src.labelsafe.database.sync_tracker import SyncTracker
from src.labelsafe.ingestion.cache_manager import CacheManager, LookupStatus
from src.labelsafe.ingestion.dailymed import parse_spl
from src.labelsafe.ingestion.errors import UpstreamNotFoundError, UpstreamUnavailableError
from src.labelsafe.ingestion.hashing import fingerprint_json
from src.labelsafe.ingestion.ingest_labels import embed_pending, ingest_labels
from src.labelsafe.ingestion.seed_loader import (
    DEFAULT_CATALOG_PATH,
    EXPECTED_CONCEPT_COUNT,
    CatalogValidationError,
    CuratedMedication,
    SeedCatalog,
    SeedConcept,
    SeedLoader,
    build_catalog,
    load_catalog,
    validate_catalog,
)
from src.labelsafe.knowledge.normalizer import CACHE_SOURCE, MedicationNormalizer

WARFARIN = "11289"


def concept(rxcui: str, name: str, **kwargs: object) -> MedicationConcept:
    return MedicationConcept.model_validate(
        {
            "rxcui": rxcui,
            "canonical_name": name,
            "term_type": "IN",
            "ingredients": [{"unii": f"U{rxcui}", "name": name}],
            **kwargs,
        }
    )


def small_catalog(n: int = 3) -> SeedCatalog:
    return SeedCatalog(
        catalog_version="test",
        generated_from="unit-test",
        concepts=[
            SeedConcept(
                priority_rank=i + 1,
                therapeutic_category="test",
                is_narrow_therapeutic_index=i == 0,
                concept=concept(str(1000 + i), f"drug{i}", synonyms=[f"Brand{i}"]),
            )
            for i in range(n)
        ],
    )


async def table_digest(session_factory: async_sessionmaker[AsyncSession]) -> str:
    async with session_factory() as session:
        rows = await session.scalars(select(MedicationConceptRecord).order_by(MedicationConceptRecord.rxcui))
        return fingerprint_json([(r.rxcui, r.content_hash, r.priority_rank) for r in rows])


async def count(session_factory: async_sessionmaker[AsyncSession], model: type) -> int:
    async with session_factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


class TestSeedCatalogFile:
    def test_catalog_file_has_500_contract_valid_concepts(self) -> None:
        catalog = load_catalog(DEFAULT_CATALOG_PATH)
        assert len(catalog.concepts) == EXPECTED_CONCEPT_COUNT
        assert all(c.concept.ingredients for c in catalog.concepts)
        nti = {c.concept.canonical_name for c in catalog.concepts if c.is_narrow_therapeutic_index}
        assert {"warfarin", "digoxin", "lithium", "levothyroxine"} <= nti
        by_name = {c.concept.canonical_name: c.concept for c in catalog.concepts}
        assert by_name["atorvastatin"].rxcui == "83367"
        assert by_name["warfarin"].rxcui == WARFARIN

    def test_validation_rejects_duplicates_gaps_and_wrong_size(self, tmp_path: Path) -> None:
        catalog = small_catalog()
        validate_catalog(catalog, expected_count=3)
        with pytest.raises(CatalogValidationError, match="expected 500"):
            validate_catalog(catalog)

        dup = catalog.model_copy(deep=True)
        dup.concepts[1].concept.rxcui = dup.concepts[0].concept.rxcui
        with pytest.raises(CatalogValidationError, match="duplicate"):
            validate_catalog(dup, expected_count=None)

        gap = catalog.model_copy(deep=True)
        gap.concepts[2].priority_rank = 9
        with pytest.raises(CatalogValidationError, match="contiguous"):
            validate_catalog(gap, expected_count=None)

        path = tmp_path / "catalog.json"
        path.write_text(json.dumps(catalog.model_dump(mode="json")))
        assert load_catalog(path, expected_count=3) == catalog


class TestSeedLoader:
    async def test_seeding_twice_is_identical_with_zero_duplicates(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        catalog = small_catalog(5)
        loader = SeedLoader(session_factory, cache=CacheManager(session_factory), batch_size=2)

        first = await loader.seed(catalog)
        digest_first = await table_digest(session_factory)
        sync_rows_first = await count(session_factory, DerivedSyncStatus)
        second = await loader.seed(catalog)

        assert (first.inserted, first.updated, first.unchanged) == (5, 0, 0)
        assert (second.inserted, second.updated, second.unchanged) == (0, 0, 5)
        assert first.catalog_hash == second.catalog_hash
        assert await table_digest(session_factory) == digest_first
        assert await count(session_factory, MedicationConceptRecord) == 5
        # Concepts feed no derived store any more (the graph was removed), so nothing is queued.
        assert await count(session_factory, DerivedSyncStatus) == sync_rows_first == 0

    async def test_changed_entry_is_updated_and_requeued(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        loader = SeedLoader(session_factory)
        catalog = small_catalog(2)
        await loader.seed(catalog)

        catalog.concepts[0].concept.synonyms.append("NewBrand")
        report = await loader.seed(catalog)
        assert (report.inserted, report.updated, report.unchanged) == (0, 1, 1)
        async with session_factory() as session:
            record = await session.get(MedicationConceptRecord, "1000")
            assert record is not None and "NewBrand" in record.synonyms
        assert await count(session_factory, DerivedSyncStatus) == 0

    async def test_seed_prewarms_normalizer_cache(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        cache = CacheManager(session_factory)
        await SeedLoader(session_factory, cache=cache).seed(small_catalog(1))

        async def must_not_fetch() -> dict[str, object]:
            raise AssertionError("seeded concept should resolve locally")

        result = await cache.get_or_fetch(CACHE_SOURCE, "US:drug0", must_not_fetch)
        assert result.status is LookupStatus.HIT
        assert result.payload is not None and result.payload["rxcui"] == "1000"

    async def test_record_round_trips_to_contract(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        catalog = small_catalog(1)
        await SeedLoader(session_factory).seed(catalog)
        async with session_factory() as session:
            record = await session.get(MedicationConceptRecord, "1000")
            assert record is not None
            assert record.to_contract() == catalog.concepts[0].concept
            assert record.is_narrow_therapeutic_index is True


class _FakeNormalizer(MedicationNormalizer):
    def __init__(self, table: dict[str, MedicationConcept | None]) -> None:
        self._table = table

    async def normalize(self, query: str, jurisdiction: str = "US") -> MedicationConcept:
        result = self._table[query]
        if result is None:
            raise UpstreamNotFoundError("RxNav", query)
        return result


class TestBuildCatalog:
    async def test_skips_unresolvable_and_duplicate_names(self) -> None:
        normalizer = _FakeNormalizer(
            {
                "warfarin": concept(WARFARIN, "warfarin"),
                "Coumadin": concept(WARFARIN, "warfarin"),
                "notadrug": None,
                "digoxin": concept("3407", "digoxin"),
                "unused": concept("1", "unused"),
            }
        )
        curated = [
            CuratedMedication("warfarin", "anticoagulant", True),
            CuratedMedication("Coumadin", "anticoagulant"),
            CuratedMedication("notadrug", "x"),
            CuratedMedication("digoxin", "cardiovascular", True),
            CuratedMedication("unused", "x"),
        ]
        catalog, skipped = await build_catalog(curated, normalizer, target_count=2, catalog_version="t")
        assert [(c.priority_rank, c.concept.rxcui) for c in catalog.concepts] == [(1, WARFARIN), (2, "3407")]
        assert len(skipped) == 2
        assert skipped[0].startswith("Coumadin: duplicate")

    async def test_too_few_resolvable_names_fails(self) -> None:
        normalizer = _FakeNormalizer({"warfarin": concept(WARFARIN, "warfarin")})
        with pytest.raises(CatalogValidationError):
            await build_catalog(
                [CuratedMedication("warfarin", "x")], normalizer, target_count=2, catalog_version="t"
            )


class TestSyncTrackerAndRepositories:
    @pytest.fixture
    async def seeded(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        await SeedLoader(session_factory).seed(
            SeedCatalog(
                catalog_version="t",
                generated_from="t",
                concepts=[
                    SeedConcept(
                        priority_rank=1,
                        therapeutic_category="anticoagulant",
                        is_narrow_therapeutic_index=True,
                        concept=MedicationConcept(
                            rxcui=WARFARIN,
                            canonical_name="warfarin",
                            term_type="IN",
                            ingredients=[IngredientReference(unii="5Q7ZVV76EI", name="warfarin")],
                        ),
                    )
                ],
            )
        )

    async def test_label_save_is_idempotent_and_feeds_both_derived_stores(
        self, session_factory: async_sessionmaker[AsyncSession], seeded: None, warfarin_spl_xml: str
    ) -> None:
        label = parse_spl(warfarin_spl_xml, rxcui=WARFARIN)
        repo = LabelRepository(session_factory)
        first = await repo.save_label(
            label.document,
            label.passages,
            label.products,
            missing_excipient_data=label.missing_excipient_data,
        )
        second = await repo.save_label(
            label.document,
            label.passages,
            label.products,
            missing_excipient_data=label.missing_excipient_data,
        )
        assert first.document_changed and first.passages_written == len(label.passages)
        assert first.products_written == 1
        assert (second.document_changed, second.passages_written, second.products_written) == (False, 0, 0)

        tracker = SyncTracker(session_factory)
        vector_queue = await tracker.get_pending_sync_entities("PGVECTOR")
        assert {q["entity_type"] for q in vector_queue} == {"PASSAGE"}
        assert len(vector_queue) == len(label.passages)
        # Only passages are queued: documents, products and concepts feed no derived store.
        assert await count(session_factory, DerivedSyncStatus) == len(label.passages)
        assert all(q["payload"] is not None for q in vector_queue)

    async def test_passage_repository_filters_by_section(
        self, session_factory: async_sessionmaker[AsyncSession], seeded: None, warfarin_spl_xml: str
    ) -> None:
        label = parse_spl(warfarin_spl_xml, rxcui=WARFARIN)
        await LabelRepository(session_factory).save_label(
            label.document, label.passages, label.products, missing_excipient_data=False
        )
        repo = PassageRepository(session_factory)
        everything = await repo.get_passages_by_rxcui(WARFARIN)
        assert sorted(p.passage_id for p in everything) == sorted(p.passage_id for p in label.passages)
        interactions = await repo.get_passages_by_rxcui(WARFARIN, loinc_section="34073-7")
        assert interactions and all(p.loinc_section_code == "34073-7" for p in interactions)
        assert await repo.get_passages_by_rxcui("0000") == []
        assert await repo.get_passage(label.passages[0].passage_id) == label.passages[0]
        assert await repo.get_passage("00000000-0000-0000-0000-000000000000") is None

    async def test_mark_synced_and_failed_lifecycle(
        self, session_factory: async_sessionmaker[AsyncSession], seeded: None
    ) -> None:
        tracker = SyncTracker(session_factory)
        await tracker.enqueue(WARFARIN, EntityType.CONCEPT, "v1", [TargetStore.PGVECTOR])
        [entry] = await tracker.get_pending_sync_entities()
        assert entry["entity_id"] == WARFARIN and entry["sync_status"] == "PENDING"
        assert entry["payload"]["canonical_name"] == "warfarin"

        await tracker.mark_failed(WARFARIN, "PGVECTOR", "embedding service down")
        [retry] = await tracker.get_pending_sync_entities()
        assert (retry["sync_status"], retry["attempt_count"]) == ("FAILED", 1)
        assert await tracker.get_pending_sync_entities(max_attempts=1) == []

        await tracker.mark_synced(WARFARIN)
        assert await tracker.get_pending_sync_entities() == []
        async with session_factory() as session:
            row = await session.scalar(select(DerivedSyncStatus))
            assert row is not None and row.sync_status is SyncState.SYNCED and row.error_message is None

    async def test_enqueue_is_idempotent_and_validates_store(
        self, session_factory: async_sessionmaker[AsyncSession], seeded: None
    ) -> None:
        tracker = SyncTracker(session_factory)
        assert await tracker.enqueue(WARFARIN, EntityType.CONCEPT, "other", [TargetStore.PGVECTOR]) == 1
        assert await tracker.enqueue(WARFARIN, EntityType.CONCEPT, "other", [TargetStore.PGVECTOR]) == 0
        with pytest.raises(ValueError):
            await tracker.get_pending_sync_entities("ELASTIC")
        with pytest.raises(LookupError):
            await tracker.mark_synced("missing", "NEO4J")

    async def test_deleted_entity_has_no_payload(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        tracker = SyncTracker(session_factory)
        await tracker.enqueue("ghost", EntityType.PRODUCT, "v1", [TargetStore.PGVECTOR])
        await tracker.enqueue("00000000-0000-0000-0000-000000000001", EntityType.PASSAGE, "v1")
        pending = await tracker.get_pending_sync_entities()
        assert {(p["entity_type"], p["payload"]) for p in pending} == {("PRODUCT", None), ("PASSAGE", None)}

    async def test_new_label_version_replaces_old_passages(
        self, session_factory: async_sessionmaker[AsyncSession], seeded: None, warfarin_spl_xml: str
    ) -> None:
        repo = LabelRepository(session_factory)
        v1 = parse_spl(warfarin_spl_xml, rxcui=WARFARIN)
        await repo.save_label(v1.document, v1.passages, v1.products, missing_excipient_data=False)

        # DailyMed publishes version 99 of the same SetID with one section fewer.
        v2 = parse_spl(
            warfarin_spl_xml.replace('versionNumber value="', 'versionNumber value="99'), rxcui=WARFARIN
        )
        assert {p.passage_id for p in v2.passages}.isdisjoint(p.passage_id for p in v1.passages)
        kept = v2.passages[:-1]
        await repo.save_label(v2.document, kept, v2.products, missing_excipient_data=False)

        stored = await PassageRepository(session_factory).get_passages_by_rxcui(WARFARIN)
        assert sorted(p.passage_id for p in stored) == sorted(p.passage_id for p in kept)

    async def test_a_new_label_document_for_the_same_drug_replaces_the_old_one(
        self, session_factory: async_sessionmaker[AsyncSession], seeded: None, warfarin_spl_xml: str
    ) -> None:
        repo = LabelRepository(session_factory)
        old = parse_spl(warfarin_spl_xml, rxcui=WARFARIN)
        await repo.save_label(old.document, old.passages, old.products, missing_excipient_data=False)

        # DailyMed now returns another manufacturer's label (a different SetID) for the same drug.
        new = parse_spl(warfarin_spl_xml.replace('setId root="', 'setId root="f', 1), rxcui=WARFARIN)
        assert new.document.document_id != old.document.document_id
        await repo.save_label(new.document, new.passages, new.products, missing_excipient_data=False)

        stored = await PassageRepository(session_factory).get_passages_by_rxcui(WARFARIN)
        assert {p.document_id for p in stored} == {new.document.document_id}
        assert sorted(p.passage_id for p in stored) == sorted(p.passage_id for p in new.passages)

    async def test_ingest_saves_labels_and_falls_back_to_openfda(
        self, session_factory: async_sessionmaker[AsyncSession], seeded: None, warfarin_spl_xml: str
    ) -> None:
        label = parse_spl(warfarin_spl_xml, rxcui=WARFARIN)

        class FakeDailyMed:
            async def search_spls(self, *, rxcui: str, page_size: int) -> list[Any]:
                if rxcui != WARFARIN:
                    raise UpstreamNotFoundError("DailyMed", rxcui)
                return [SimpleNamespace(setid=label.document.document_id)]

            async def fetch_label(self, setid: str, *, rxcui: str) -> Any:
                return label

        class FakeOpenFDA:
            async def fetch_labels_for_generic(self, name: str, **kwargs: Any) -> list[Any]:
                if name == "broken":
                    raise UpstreamUnavailableError("openFDA", "500")
                raise UpstreamNotFoundError("openFDA", name)

        concepts = [
            MedicationConcept(rxcui=WARFARIN, canonical_name="warfarin", term_type="IN"),
            MedicationConcept(rxcui="1", canonical_name="unknown", term_type="IN"),
            MedicationConcept(rxcui="2", canonical_name="broken", term_type="IN"),
        ]
        report = await ingest_labels(session_factory, concepts, FakeDailyMed(), FakeOpenFDA())  # type: ignore[arg-type]
        assert (report.labels_saved, report.passages_written) == (1, len(label.passages))
        assert (report.not_found, report.failed) == (["1"], ["2"])

        class Sink:
            def __init__(self) -> None:
                self.ids: list[str] = []

            async def upsert(self, passages: Any) -> int:
                self.ids += [p.passage_id for p in passages]
                return len(passages)

        sink = Sink()
        assert await embed_pending(session_factory, sink, batch_size=2) == len(label.passages)
        assert sorted(sink.ids) == sorted(p.passage_id for p in label.passages)
        assert await SyncTracker(session_factory).get_pending_sync_entities() == []
        assert await embed_pending(session_factory, sink) == 0  # idempotent once drained


def test_pick_label_skips_homeopathic_kits_and_long_mixtures() -> None:
    from src.labelsafe.ingestion.ingest_labels import pick_label

    hits = [
        SimpleNamespace(
            setid="mix", title="ENERGY CATALYST- viscum album, lithium, cuprum, bismuthum liquid"
        ),
        SimpleNamespace(setid="homeo", title="LITHIUM CARBONATE (HOMEOPATHIC) pellet"),
        SimpleNamespace(setid="kit", title="LITHIUM CARBONATE KIT"),
        SimpleNamespace(setid="rx", title="LITHIUM CARBONATE capsule"),
    ]
    assert pick_label(hits, "lithium").setid == "rx"
    assert (
        pick_label([SimpleNamespace(setid="only")], "lithium").setid == "only"
    )  # titleless fakes still work
