"""Async SQLAlchemy engine and session factory."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import Settings


def build_engine(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create async engine and return (engine, session_factory).

    Caller is responsible for calling `await engine.dispose()` on shutdown.
    """
    engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=5)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory
