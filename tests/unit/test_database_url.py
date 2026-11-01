"""The database URL Neon provides is accepted as-is (libpq style, converted for asyncpg)."""

import pytest

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
