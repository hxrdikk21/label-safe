"""Shared fixtures for Workstream 1 unit tests. All network I/O is mocked with respx."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.labelsafe.database.connection import create_all, create_engine, create_session_factory
from src.labelsafe.ingestion.http import RetryPolicy

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClock:
    """Deterministic monotonic clock whose ``sleep`` advances time instead of blocking."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeWallClock:
    """Deterministic UTC wall clock for TTL tests."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def wall_clock() -> FakeWallClock:
    return FakeWallClock()


@pytest.fixture
def no_wait_policy() -> RetryPolicy:
    return RetryPolicy(max_attempts=3, base_delay=0.0, max_delay=0.0)


@pytest.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'labelsafe.db'}")
    await create_all(engine)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
def warfarin_spl_xml() -> str:
    return (FIXTURES / "spl_warfarin_synthetic.xml").read_text(encoding="utf-8")
