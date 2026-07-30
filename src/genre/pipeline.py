"""Resolve a new like's genre and persist it.

Shared by both entrypoints — the Telegram bot (`src.main`) and the sidecar
(`src.sidecar.context`) — so the resolve-then-store step cannot drift apart
between them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from sqlalchemy import update

from src.db.models import LikedTrack
from src.genre.resolver import GenreResult, resolve_genre

if TYPE_CHECKING:
    import discogs_client
    import pylast
    import spotipy
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger()


async def resolve_and_store_genre(
    track: LikedTrack,
    *,
    sp: spotipy.Spotify,
    discogs: discogs_client.Client,
    lastfm: pylast.LastFMNetwork,
    session_factory: async_sessionmaker[AsyncSession],
) -> GenreResult:
    """Run the genre waterfall for ``track`` and write the outcome to the DB."""
    genre_result = await resolve_genre(
        track_id=track.spotify_track_id,
        artist_name=track.artist_name or "",
        track_name=track.track_name or "",
        sp=sp,
        discogs=discogs,
        lastfm=lastfm,
        session_factory=session_factory,
    )

    async with session_factory() as session:
        await session.execute(
            update(LikedTrack)
            .where(LikedTrack.id == track.id)
            .values(
                detected_genre=genre_result.genre_key,
                genre_source=genre_result.source,
            )
        )
        await session.commit()

    logger.debug(
        "genre.stored",
        track=track.spotify_track_id,
        genre=genre_result.genre_key,
        source=genre_result.source,
    )
    return genre_result
