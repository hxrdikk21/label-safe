"""Cache-first lookup tests: hits, misses, 7-day negative caching and outage behaviour."""

from datetime import timedelta

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.labelsafe.database.models import CacheEntryStatus, ExternalLookupCache
from src.labelsafe.ingestion.cache_manager import (
    NEGATIVE_CACHE_TTL,
    CacheManager,
    Fetcher,
    LookupStatus,
    build_cache_key,
)
from src.labelsafe.ingestion.dailymed import DEFAULT_BASE_URL as DAILYMED_URL
from src.labelsafe.ingestion.dailymed import DailyMedClient
from src.labelsafe.ingestion.errors import UpstreamUnavailableError
from src.labelsafe.ingestion.http import RetryPolicy
from src.labelsafe.ingestion.rxnav import DEFAULT_BASE_URL as RXNAV_URL
from src.labelsafe.ingestion.rxnav import RxNavClient
from src.labelsafe.knowledge.normalizer import MedicationNormalizer, MedicationNotFoundError
from tests.unit.conftest import FakeWallClock
from tests.unit.rxnav_mocks import mock_atorvastatin

SETID = "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d"
SPL_URL = f"{DAILYMED_URL}/spls/{SETID}.xml"


@pytest.fixture
def cache(session_factory: async_sessionmaker[AsyncSession], wall_clock: FakeWallClock) -> CacheManager:
    return CacheManager(session_factory, clock=wall_clock)


@pytest.fixture
def dailymed(http_client: httpx.AsyncClient, no_wait_policy: RetryPolicy) -> DailyMedClient:
    return DailyMedClient(http_client, retry_policy=no_wait_policy)


def spl_fetcher(client: DailyMedClient) -> Fetcher:
    async def fetch() -> dict[str, object]:
        return {"xml": await client.fetch_spl_xml(SETID)}

    return fetch


async def cache_rows(session_factory: async_sessionmaker[AsyncSession]) -> list[ExternalLookupCache]:
    async with session_factory() as session:
        return list(await session.scalars(select(ExternalLookupCache)))


class TestCacheFirstLookup:
    @respx.mock
    async def test_cache_miss_makes_one_http_call_and_writes_cache(
        self,
        cache: CacheManager,
        dailymed: DailyMedClient,
        session_factory: async_sessionmaker[AsyncSession],
        warfarin_spl_xml: str,
    ) -> None:
        route = respx.get(SPL_URL).respond(200, text=warfarin_spl_xml)
        result = await cache.get_or_fetch("dailymed", f"spl:{SETID}", spl_fetcher(dailymed))

        assert result.status is LookupStatus.FETCHED
        assert result.payload == {"xml": warfarin_spl_xml}
        assert route.call_count == 1
        [row] = await cache_rows(session_factory)
        assert row.status is CacheEntryStatus.POSITIVE
        assert row.payload_hash is not None and len(row.payload_hash) == 64

    @respx.mock
    async def test_cache_hit_makes_zero_http_calls(
        self, cache: CacheManager, dailymed: DailyMedClient, warfarin_spl_xml: str
    ) -> None:
        route = respx.get(SPL_URL).respond(200, text=warfarin_spl_xml)
        await cache.get_or_fetch("dailymed", f"spl:{SETID}", spl_fetcher(dailymed))
        route.reset()

        result = await cache.get_or_fetch("dailymed", f"SPL:{SETID}  ", spl_fetcher(dailymed))
        assert result.status is LookupStatus.HIT
        assert result.from_cache is True
        assert result.payload == {"xml": warfarin_spl_xml}
        assert route.call_count == 0

    @respx.mock
    async def test_negative_cache_ttl_is_seven_days(
        self,
        cache: CacheManager,
        dailymed: DailyMedClient,
        wall_clock: FakeWallClock,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        assert timedelta(days=7) == NEGATIVE_CACHE_TTL
        route = respx.get(SPL_URL).respond(404)

        first = await cache.get_or_fetch("dailymed", f"spl:{SETID}", spl_fetcher(dailymed))
        assert first.status is LookupStatus.NOT_FOUND and first.payload is None
        assert route.call_count == 1
        [row] = await cache_rows(session_factory)
        assert row.status is CacheEntryStatus.NEGATIVE

        wall_clock.advance(timedelta(days=7) - timedelta(seconds=1))
        cached = await cache.get_or_fetch("dailymed", f"spl:{SETID}", spl_fetcher(dailymed))
        assert cached.status is LookupStatus.NOT_FOUND and cached.from_cache is True
        assert route.call_count == 1

        wall_clock.advance(timedelta(seconds=2))
        expired = await cache.get_or_fetch("dailymed", f"spl:{SETID}", spl_fetcher(dailymed))
        assert expired.status is LookupStatus.NOT_FOUND and expired.from_cache is False
        assert route.call_count == 2

    @respx.mock
    async def test_outage_without_snapshot_is_explicit_and_not_cached(
        self, cache: CacheManager, dailymed: DailyMedClient, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        route = respx.get(SPL_URL).respond(503)
        result = await cache.get_or_fetch("dailymed", f"spl:{SETID}", spl_fetcher(dailymed))
        assert result.status is LookupStatus.UNAVAILABLE
        assert result.payload is None and result.has_payload is False
        assert result.error is not None
        assert await cache_rows(session_factory) == []

        await cache.get_or_fetch("dailymed", f"spl:{SETID}", spl_fetcher(dailymed))
        assert route.call_count == 6  # an outage is never negatively cached: every lookup retries upstream

    @respx.mock
    async def test_outage_falls_back_to_stale_snapshot(
        self, cache: CacheManager, dailymed: DailyMedClient, wall_clock: FakeWallClock, warfarin_spl_xml: str
    ) -> None:
        respx.get(SPL_URL).mock(
            side_effect=[httpx.Response(200, text=warfarin_spl_xml)] + [httpx.Response(500)] * 3
        )
        await cache.get_or_fetch("dailymed", f"spl:{SETID}", spl_fetcher(dailymed))
        wall_clock.advance(cache.positive_ttl + timedelta(minutes=1))

        result = await cache.get_or_fetch("dailymed", f"spl:{SETID}", spl_fetcher(dailymed))
        assert result.status is LookupStatus.STALE_FALLBACK
        assert result.payload == {"xml": warfarin_spl_xml}
        assert result.error is not None

    @respx.mock
    async def test_expired_positive_entry_is_refreshed(
        self, cache: CacheManager, dailymed: DailyMedClient, wall_clock: FakeWallClock
    ) -> None:
        route = respx.get(SPL_URL).mock(
            side_effect=[httpx.Response(200, text="v1"), httpx.Response(200, text="v2")]
        )
        await cache.get_or_fetch("dailymed", f"spl:{SETID}", spl_fetcher(dailymed))
        wall_clock.advance(cache.positive_ttl)
        result = await cache.get_or_fetch("dailymed", f"spl:{SETID}", spl_fetcher(dailymed))
        assert result.status is LookupStatus.FETCHED
        assert result.payload == {"xml": "v2"}
        assert route.call_count == 2

    async def test_put_is_idempotent_and_invalidate_and_purge(
        self,
        cache: CacheManager,
        wall_clock: FakeWallClock,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        await cache.put("rxnav", "k1", {"a": 1})
        [before] = await cache_rows(session_factory)
        wall_clock.advance(timedelta(hours=1))
        await cache.put("rxnav", "k1", {"a": 1})
        [after] = await cache_rows(session_factory)
        assert after.fetched_at == before.fetched_at  # unchanged content -> no rewrite

        await cache.put("rxnav", "k1", {"a": 2})
        [changed] = await cache_rows(session_factory)
        assert changed.payload == {"a": 2}

        await cache.put("rxnav", "k2", {"b": 1}, ttl=timedelta(minutes=5))
        await cache.invalidate("rxnav", "k1")
        assert [r.cache_key for r in await cache_rows(session_factory)] == ["rxnav:k2"]
        wall_clock.advance(timedelta(minutes=10))
        assert await cache.purge_expired() == 1
        assert await cache_rows(session_factory) == []

    def test_long_keys_are_hashed(self) -> None:
        key = build_cache_key("RxNav", "x" * 400)
        assert key.startswith("rxnav:sha256:") and len(key) <= 255
        assert build_cache_key("RxNav", "  Lipitor   10 mg ") == "rxnav:lipitor 10 mg"


class TestNormalizerCacheFirst:
    @pytest.fixture
    def cached_normalizer(
        self, http_client: httpx.AsyncClient, cache: CacheManager, no_wait_policy: RetryPolicy
    ) -> MedicationNormalizer:
        return MedicationNormalizer(RxNavClient(http_client, retry_policy=no_wait_policy), cache)

    @respx.mock
    async def test_second_lookup_is_served_locally(self, cached_normalizer: MedicationNormalizer) -> None:
        mock_atorvastatin()
        first = await cached_normalizer.normalize("Lipitor")
        calls_after_first = len(respx.calls)
        assert calls_after_first > 0

        second = await cached_normalizer.normalize("lipitor")
        assert second == first
        assert len(respx.calls) == calls_after_first

    @respx.mock
    async def test_not_found_is_negatively_cached(self, cached_normalizer: MedicationNormalizer) -> None:
        name_route = respx.get(f"{RXNAV_URL}/rxcui.json").respond(200, json={"idGroup": {}})
        respx.get(f"{RXNAV_URL}/approximateTerm.json").respond(200, json={"approximateGroup": {}})
        for _ in range(2):
            with pytest.raises(MedicationNotFoundError):
                await cached_normalizer.normalize("xyzzyq")
        assert name_route.call_count == 1

    @respx.mock
    async def test_outage_raises_rather_than_returning_empty_concept(
        self, cached_normalizer: MedicationNormalizer
    ) -> None:
        respx.get(f"{RXNAV_URL}/rxcui.json").respond(502)
        with pytest.raises(UpstreamUnavailableError):
            await cached_normalizer.normalize("Lipitor")
