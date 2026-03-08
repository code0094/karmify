"""Async SQLAlchemy engine and session factory."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import Settings


def build_engine(settings: Settings) -> async_sessionmaker[AsyncSession]:
    """Create async engine and return a session factory."""
    engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=5)
    return async_sessionmaker(engine, expire_on_commit=False)
