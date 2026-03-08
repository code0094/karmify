"""Map raw genre strings to genre_key using aliases from DB."""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db import repos

logger = structlog.get_logger()


async def map_to_genre_key(
    session_factory: async_sessionmaker[AsyncSession],
    raw_genres: list[str],
) -> str | None:
    """Try to match any of the raw genre strings to a known genre_key via aliases."""
    async with session_factory() as session:
        for raw in raw_genres:
            genre_key = await repos.find_genre_key(session, raw)
            if genre_key:
                logger.debug("mapper.matched", raw=raw, genre_key=genre_key)
                return genre_key

    logger.debug("mapper.no_match", raw_genres=raw_genres)
    return None
