"""Vercel/Neon specifics: the database URL Neon provides, and the client IP behind Vercel's proxy."""

import pytest
from starlette.requests import Request

from src.labelsafe.api.dependencies import client_ip
from src.labelsafe.core.config import Settings


def test_neon_url_becomes_an_asyncpg_url() -> None:
    neon = "postgres://user:pa%40ss@ep-cool-1.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    assert Settings(database_url=neon).database_url == (
        "postgresql+asyncpg://user:pa%40ss@ep-cool-1.eu-central-1.aws.neon.tech/neondb?ssl=require"
    )


@pytest.mark.parametrize(
    "url", ["postgresql+asyncpg://u:p@localhost:5432/db", "sqlite+aiosqlite:///:memory:", ""]
)
def test_sqlalchemy_and_empty_urls_are_left_alone(url: str) -> None:
    assert Settings(database_url=url).database_url == url


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": ("10.0.0.1", 1234)})


def test_client_ip_uses_vercel_forwarding_headers_only_on_vercel(monkeypatch: pytest.MonkeyPatch) -> None:
    spoofed = _request({"x-forwarded-for": "6.6.6.6"})
    monkeypatch.delenv("VERCEL", raising=False)
    assert client_ip(spoofed) == "10.0.0.1"  # headers are client-controlled off Vercel
    monkeypatch.setenv("VERCEL", "1")
    assert client_ip(_request({"x-real-ip": "203.0.113.7"})) == "203.0.113.7"
    assert client_ip(_request({"x-forwarded-for": "198.51.100.2, 10.1.1.1"})) == "198.51.100.2"
    assert client_ip(_request({})) == "10.0.0.1"
