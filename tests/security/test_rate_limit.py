"""Per-IP request limits (429 + Retry-After) and the daily Gemini budget."""

from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from src.labelsafe.api import dependencies
from src.labelsafe.api.main import app
from src.labelsafe.auth.rate_limit import MemoryCounters, RequestLimiter
from src.labelsafe.core.config import get_settings

MEDS = [{"rxcui": "11289", "canonical_name": "warfarin", "term_type": "IN"}]


async def test_fixed_window_allows_the_limit_then_reports_seconds_to_wait() -> None:
    now = [100.0]
    limiter = RequestLimiter(MemoryCounters(clock=lambda: now[0]))
    assert [await limiter.hit("k", 2, 60) for _ in range(2)] == [None, None]
    assert await limiter.hit("k", 2, 60) == 20  # window [60, 120) ends in 20 s
    now[0] = 120.0
    assert await limiter.hit("k", 2, 60) is None  # a new window


@pytest.fixture
def limited(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    limiter = RequestLimiter(MemoryCounters())
    app.dependency_overrides[dependencies.get_request_limiter] = lambda: limiter
    monkeypatch.setattr(get_settings(), "rate_limit_chat_per_minute", 2)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_chat_returns_429_with_retry_after_once_the_ip_is_over_its_limit(limited: TestClient) -> None:
    body = {"query": "is this risky?", "medications": MEDS}
    codes = [limited.post("/api/v1/chat/message", json=body).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    res = limited.post("/api/v1/chat/message", json=body)
    assert res.status_code == 429 and int(res.headers["retry-after"]) > 0
    assert "Too many requests" in res.json()["detail"]


async def test_gemini_is_withheld_once_the_daily_budget_is_spent(monkeypatch: pytest.MonkeyPatch) -> None:
    chat = object()
    monkeypatch.setattr(dependencies, "_gemini", lambda: chat)
    monkeypatch.setattr(get_settings(), "gemini_daily_budget", 2)
    limiter = RequestLimiter(MemoryCounters())
    got = [await dependencies.get_chat_model(limiter) for _ in range(3)]
    assert got == [chat, chat, None]  # the third request quotes labels instead of calling Gemini


def test_no_gemini_key_means_no_chat_model() -> None:
    from src.labelsafe.core.config import Settings
    from src.labelsafe.rag.generator import get_chat_model

    assert get_chat_model(Settings(llm_backend="gemini", gemini_api_key=None)) is None
