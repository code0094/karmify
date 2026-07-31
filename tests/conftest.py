"""Shared test fixtures — mocks for Spotify, Discogs, Last.fm, DB."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.config import Settings
from src.db.models import Base, GenrePlaylist, LikedTrack

# Minimal required settings (everything except the optional groups).
_REQUIRED_SETTINGS: dict[str, Any] = {
    "spotify_client_id": "cid",
    "spotify_client_secret": "secret",
    "discogs_user_token": "discogs-token",
    "lastfm_api_key": "lastfm-key",
    "lastfm_api_secret": "lastfm-secret",
    "database_url": "postgresql+asyncpg://user:pass@localhost:5432/test",
}


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    """Build a valid Settings object without reading .env; override via kwargs."""

    def _make(**overrides: Any) -> Settings:
        return Settings(_env_file=None, **{**_REQUIRED_SETTINGS, **overrides})

    return _make


@pytest.fixture
async def db_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Real in-memory SQLite session factory with the full schema created.

    Prod runs PostgreSQL; SQLite here verifies query logic, not PG specifics
    (`SELECT FOR UPDATE` is not rendered by the SQLite dialect, and
    ``DateTime(timezone=True)`` comes back naive). StaticPool is required so
    ``create_all`` and the sessions share the same in-memory database.
    """
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def db_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """One session from db_session_factory (see its fidelity caveats)."""
    async with db_session_factory() as session:
        yield session


@pytest.fixture
def mock_spotify() -> MagicMock:
    """Mock spotipy.Spotify client."""
    sp = MagicMock()
    sp.track.return_value = {
        "id": "track123",
        "name": "Akephale",
        "artists": [{"id": "artist1", "name": "ROD"}],
    }
    sp.artists.return_value = {
        "artists": [{"id": "artist1", "name": "ROD", "genres": ["hardgroove", "techno"]}]
    }
    sp.current_user_saved_tracks.return_value = {
        "items": [
            {
                "added_at": "2026-03-08T12:00:00Z",
                "track": {
                    "id": "track123",
                    "name": "Akephale",
                    "artists": [{"name": "ROD"}],
                },
            }
        ]
    }
    sp.playlist_tracks.return_value = {"items": []}
    sp.playlist_add_items.return_value = None
    return sp


@pytest.fixture
def mock_discogs() -> MagicMock:
    """Mock discogs_client.Client."""
    client = MagicMock()
    result = MagicMock()
    result.genres = ["Electronic"]
    result.styles = ["Hardgroove", "Techno"]
    # NB: MagicMock(name=...) sets the MOCK's name, not .name — build explicitly.
    label = MagicMock()
    label.name = "Planet Rhythm"
    result.labels = [label]
    result.count = 1
    search_results = MagicMock()
    search_results.__getitem__ = MagicMock(return_value=result)
    search_results.count = 1
    client.search.return_value = search_results
    return client


@pytest.fixture
def mock_lastfm() -> MagicMock:
    """Mock pylast.LastFMNetwork."""
    network = MagicMock()
    tag1 = MagicMock()
    tag1.item.get_name.return_value = "techno"
    tag1.weight = 90
    tag2 = MagicMock()
    tag2.item.get_name.return_value = "hardgroove"
    tag2.weight = 75
    track = MagicMock()
    track.get_top_tags.return_value = [tag1, tag2]
    network.get_track.return_value = track
    return network


@pytest.fixture
def sample_track() -> LikedTrack:
    """Sample LikedTrack for testing."""
    return LikedTrack(
        id=1,
        spotify_track_id="track123",
        track_name="Akephale",
        artist_name="ROD",
        liked_by="karma",
        liked_at=datetime(2026, 3, 8, 12, 0, tzinfo=UTC),
    )


@pytest.fixture
def sample_playlists() -> list[GenrePlaylist]:
    """Sample genre playlists."""
    return [
        GenrePlaylist(
            id=1,
            genre_key="hardgroove",
            playlist_id="pl_hg",
            display_name="Hardgroove",
            emoji="🔊",
        ),
        GenrePlaylist(
            id=2,
            genre_key="acid",
            playlist_id="pl_acid",
            display_name="Acid",
            emoji="🧪",
        ),
        GenrePlaylist(
            id=3,
            genre_key="jungle",
            playlist_id="pl_jungle",
            display_name="Jungle",
            emoji="🌴",
        ),
        GenrePlaylist(
            id=4,
            genre_key="electro",
            playlist_id="pl_electro",
            display_name="Electro",
            emoji="🔌",
        ),
    ]


@pytest.fixture
def mock_session_factory() -> AsyncMock:
    """Mock async session factory."""
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory
