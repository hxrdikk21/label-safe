"""
Local-first (cache-first) lookup for external medication sources.

Lookup order:
  1. A fresh PostgreSQL cache entry is returned with zero network calls.
     Fresh negative entries (genuine upstream 404s) short-circuit for 7 days.
  2. Otherwise the upstream fetcher is called once and the result is cached.
  3. If the upstream is unavailable (5xx, timeout, malformed payload) the
     last known snapshot is returned as ``STALE_FALLBACK``; with no snapshot
     the explicit ``UNAVAILABLE`` state is returned. An outage is never cached
     and never converted into an empty ("safe") answer.
"""

import enum
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.rxguard.database.models import CacheEntryStatus, ExternalLookupCache
from src.rxguard.ingestion.errors import UpstreamNotFoundError, UpstreamUnavailableError
from src.rxguard.ingestion.hashing import fingerprint_json, sha256_hex

logger = logging.getLogger(__name__)

NEGATIVE_CACHE_TTL: Final = timedelta(days=7)
POSITIVE_CACHE_TTL: Final = timedelta(days=30)
_MAX_KEY_LENGTH: Final = 255

Fetcher = Callable[[], Awaitable[dict[str, Any]]]
Clock = Callable[[], datetime]


class LookupStatus(enum.StrEnum):
    HIT = "HIT"
    FETCHED = "FETCHED"
    NOT_FOUND = "NOT_FOUND"
    STALE_FALLBACK = "STALE_FALLBACK"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class LookupResult:
    """Outcome of a cache-first lookup. ``payload`` is None for NOT_FOUND and UNAVAILABLE."""

    status: LookupStatus
    cache_key: str
    payload: dict[str, Any] | None = None
    error: str | None = None
    from_cache: bool = False

    @property
    def has_payload(self) -> bool:
        return self.payload is not None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def build_cache_key(source: str, key: str) -> str:
    """Builds a normalized cache key, hashing keys that would exceed the column width."""
    normalized = f"{source.lower()}:{' '.join(key.lower().split())}"
    if len(normalized) <= _MAX_KEY_LENGTH:
        return normalized
    return f"{source.lower()}:sha256:{sha256_hex(normalized)}"


class CacheManager:
    """Cache-first lookup worker backed by the ``external_lookup_cache`` table."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        positive_ttl: timedelta = POSITIVE_CACHE_TTL,
        negative_ttl: timedelta = NEGATIVE_CACHE_TTL,
        clock: Clock = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self.positive_ttl = positive_ttl
        self.negative_ttl = negative_ttl
        self._clock = clock

    async def get_or_fetch(self, source: str, key: str, fetcher: Fetcher) -> LookupResult:
        """Returns a cached result when fresh, otherwise calls ``fetcher`` exactly once."""
        cache_key = build_cache_key(source, key)
        now = self._clock()
        async with self._session_factory() as session:
            entry = await session.get(ExternalLookupCache, cache_key)
            if entry is not None and _aware(entry.expires_at) > now:
                if entry.status is CacheEntryStatus.NEGATIVE:
                    return LookupResult(LookupStatus.NOT_FOUND, cache_key, from_cache=True)
                return LookupResult(LookupStatus.HIT, cache_key, payload=entry.payload, from_cache=True)
            stale_payload = (
                entry.payload if entry is not None and entry.status is CacheEntryStatus.POSITIVE else None
            )

        try:
            payload = await fetcher()
        except UpstreamNotFoundError as exc:
            await self._store(cache_key, source, CacheEntryStatus.NEGATIVE, None, now, self.negative_ttl)
            return LookupResult(LookupStatus.NOT_FOUND, cache_key, error=str(exc))
        except UpstreamUnavailableError as exc:
            logger.error("Upstream %s unavailable for %s: %s", source, cache_key, exc)
            if stale_payload is not None:
                return LookupResult(
                    LookupStatus.STALE_FALLBACK,
                    cache_key,
                    payload=stale_payload,
                    error=str(exc),
                    from_cache=True,
                )
            return LookupResult(LookupStatus.UNAVAILABLE, cache_key, error=str(exc))

        await self._store(cache_key, source, CacheEntryStatus.POSITIVE, payload, now, self.positive_ttl)
        return LookupResult(LookupStatus.FETCHED, cache_key, payload=payload)

    async def put(self, source: str, key: str, payload: dict[str, Any], ttl: timedelta | None = None) -> None:
        """
        Pre-warms a positive entry (used by the seeder so seeded concepts resolve offline).
        A fresh entry with identical content is left untouched, keeping re-seeding write-free.
        """
        cache_key = build_cache_key(source, key)
        now = self._clock()
        async with self._session_factory() as session:
            entry = await session.get(ExternalLookupCache, cache_key)
            if (
                entry is not None
                and entry.status is CacheEntryStatus.POSITIVE
                and entry.payload_hash == fingerprint_json(payload)
                and _aware(entry.expires_at) > now
            ):
                return
        await self._store(
            cache_key, source, CacheEntryStatus.POSITIVE, payload, now, ttl or self.positive_ttl
        )

    async def invalidate(self, source: str, key: str) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                delete(ExternalLookupCache).where(
                    ExternalLookupCache.cache_key == build_cache_key(source, key)
                )
            )

    async def purge_expired(self) -> int:
        """Deletes expired entries and returns the number removed."""
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                delete(ExternalLookupCache).where(ExternalLookupCache.expires_at <= self._clock())
            )
        return int(getattr(result, "rowcount", 0) or 0)

    async def _store(
        self,
        cache_key: str,
        source: str,
        status: CacheEntryStatus,
        payload: dict[str, Any] | None,
        now: datetime,
        ttl: timedelta,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await session.merge(
                ExternalLookupCache(
                    cache_key=cache_key,
                    source=source,
                    status=status,
                    payload=payload,
                    payload_hash=fingerprint_json(payload) if payload is not None else None,
                    fetched_at=now,
                    expires_at=now + ttl,
                )
            )
