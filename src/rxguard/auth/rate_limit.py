"""
Rate limiting: login brute-force protection, per-IP request limits and the daily Gemini budget.

All three count events in fixed windows (``bucket = now // window``) through one counter store:
``MemoryCounters`` for development and tests, ``SqlCounters`` (the ``rate_limit_counters`` table)
in production, so limits hold across restarts and across several API workers or replicas.
"""

from __future__ import annotations

import math
import random
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.rxguard.database.models import RateLimitCounter


class Counters(Protocol):
    async def incr(self, key: str, window_s: int) -> tuple[int, int]:
        """Counts one event; returns (events in the current window, seconds until it ends)."""
        ...

    async def peek(self, key: str, window_s: int) -> tuple[int, int]: ...

    async def clear(self, key: str) -> None: ...


def _bucket(now: float, window_s: int) -> tuple[int, int]:
    bucket = int(now // window_s)
    return bucket, max(1, math.ceil((bucket + 1) * window_s - now))


class MemoryCounters:
    """Per-process counters (development, tests, and any run without a database)."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._counts: dict[tuple[str, int], int] = {}
        self._lock = threading.Lock()

    async def incr(self, key: str, window_s: int) -> tuple[int, int]:
        bucket, retry = _bucket(self._clock(), window_s)
        with self._lock:
            # Drop this key's finished windows so memory stays bounded.
            for old in [k for k in self._counts if k[0] == key and k[1] < bucket]:
                del self._counts[old]
            self._counts[(key, bucket)] = self._counts.get((key, bucket), 0) + 1
            return self._counts[(key, bucket)], retry

    async def peek(self, key: str, window_s: int) -> tuple[int, int]:
        bucket, retry = _bucket(self._clock(), window_s)
        with self._lock:
            return self._counts.get((key, bucket), 0), retry

    async def clear(self, key: str) -> None:
        with self._lock:
            for k in [k for k in self._counts if k[0] == key]:
                del self._counts[k]


class SqlCounters:
    """Counters in PostgreSQL (``rate_limit_counters``): one atomic upsert per event."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def incr(self, key: str, window_s: int) -> tuple[int, int]:
        bucket, retry = _bucket(time.time(), window_s)
        statement = (
            insert(RateLimitCounter)
            .values(key=key, bucket=bucket, count=1)
            .on_conflict_do_update(
                index_elements=["key", "bucket"],
                set_={"count": RateLimitCounter.count + 1, "updated_at": datetime.now(UTC)},
            )
            .returning(RateLimitCounter.count)
        )
        async with self._session_factory() as session, session.begin():
            count = (await session.execute(statement)).scalar_one()
            if random.random() < 0.01:  # noqa: S311 - housekeeping sample, not security
                cutoff = datetime.now(UTC) - timedelta(days=2)
                await session.execute(delete(RateLimitCounter).where(RateLimitCounter.updated_at < cutoff))
        return int(count), retry

    async def peek(self, key: str, window_s: int) -> tuple[int, int]:
        bucket, retry = _bucket(time.time(), window_s)
        async with self._session_factory() as session:
            count = await session.scalar(
                select(RateLimitCounter.count).where(
                    RateLimitCounter.key == key, RateLimitCounter.bucket == bucket
                )
            )
        return int(count or 0), retry

    async def clear(self, key: str) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(delete(RateLimitCounter).where(RateLimitCounter.key == key))


class RequestLimiter:
    """Allows ``limit`` events per key per window; ``hit`` returns seconds to wait once exceeded."""

    def __init__(self, counters: Counters) -> None:
        self.counters = counters

    async def hit(self, key: str, limit: int, window_s: int) -> int | None:
        count, retry = await self.counters.incr(key, window_s)
        return retry if count > limit else None


class LoginRateLimiter:
    """Failed logins per key (username + client address): locked out after ``max_failures`` in a
    window, cleared by a successful login."""

    def __init__(
        self,
        max_failures: int = 5,
        window_seconds: int = 900,
        clock: Callable[[], float] = time.time,
        counters: Counters | None = None,
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.counters = counters or MemoryCounters(clock)

    async def retry_after(self, key: str) -> int:
        """Seconds until ``key`` may try again; 0 when not locked out."""
        count, retry = await self.counters.peek(f"login|{key}", self.window_seconds)
        return retry if count >= self.max_failures else 0

    async def record_failure(self, key: str) -> None:
        await self.counters.incr(f"login|{key}", self.window_seconds)

    async def reset(self, key: str) -> None:
        await self.counters.clear(f"login|{key}")
