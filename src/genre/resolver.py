"""Genre resolution waterfall: Spotify → Discogs → Last.fm → manual."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from src.genre import discogs_lookup, lastfm_tags, spotify_genres
from src.genre.mapper import map_to_genre_key

if TYPE_CHECKING:
    import discogs_client
    import pylast
    import spotipy
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger()


@dataclass
class GenreResult:
    """Result of genre resolution."""

    genre_key: str | None
    raw_genre: str | None
    source: str  # 'spotify' | 'discogs' | 'lastfm' | 'manual'
    label: str | None = None  # record label from Discogs

    def has_match(self) -> bool:
        return self.genre_key is not None


async def resolve_genre(
    track_id: str,
    artist_name: str,
    track_name: str,
    sp: spotipy.Spotify,
    discogs: discogs_client.Client,
    lastfm: pylast.LastFMNetwork,
    session_factory: async_sessionmaker[AsyncSession],
) -> GenreResult:
    """Run the genre resolution waterfall for a track."""

    # Fetch label once (not per waterfall level)
    label = await discogs_lookup.get_label(discogs, artist_name, track_name)

    # Level 1: Spotify artist genres
    raw_genres = await spotify_genres.get_artist_genres(sp, track_id)
    if raw_genres:
        genre_key = await map_to_genre_key(session_factory, raw_genres)
        if genre_key:
            return GenreResult(
                genre_key=genre_key,
                raw_genre=raw_genres[0],
                source="spotify",
                label=label,
            )

    # Level 2: Discogs genre + style
    raw_genres = await discogs_lookup.search_genre(discogs, artist_name, track_name)
    if raw_genres:
        genre_key = await map_to_genre_key(session_factory, raw_genres)
        if genre_key:
            return GenreResult(
                genre_key=genre_key,
                raw_genre=raw_genres[0],
                source="discogs",
                label=label,
            )

    # Level 3: Last.fm tags
    raw_genres = await lastfm_tags.get_top_tags(lastfm, artist_name, track_name)
    if raw_genres:
        genre_key = await map_to_genre_key(session_factory, raw_genres)
        if genre_key:
            return GenreResult(
                genre_key=genre_key,
                raw_genre=raw_genres[0],
                source="lastfm",
                label=label,
            )

    # Level 4: manual — no genre found
    logger.info("genre.manual_needed", artist=artist_name, track=track_name)
    return GenreResult(genre_key=None, raw_genre=None, source="manual", label=label)
