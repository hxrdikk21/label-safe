"""Async SQLAlchemy engine and session factory construction."""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.rxguard.database.models import Base


def create_engine(
    url: str, *, pool_size: int = 10, max_overflow: int = 20, echo: bool = False
) -> AsyncEngine:
    """Creates an async engine; pool sizing only applies to server databases such as PostgreSQL."""
    if url.startswith("sqlite"):
        return create_async_engine(url, echo=echo)
    return create_async_engine(
        url, pool_size=pool_size, max_overflow=max_overflow, pool_pre_ping=True, echo=echo
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Returns a session factory whose objects stay usable after commit."""
    return async_sessionmaker(engine, expire_on_commit=False)


def engine_from_settings() -> AsyncEngine:
    """Builds the application engine from :class:`rxguard.core.config.Settings`."""
    from src.rxguard.core.config import get_settings

    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )


async def create_all(engine: AsyncEngine) -> None:
    """Creates all canonical tables (development/tests only; production uses Alembic)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
