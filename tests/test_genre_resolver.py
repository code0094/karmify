"""Tests for genre resolver waterfall."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.genre.resolver import resolve_genre


@pytest.mark.asyncio
async def test_resolve_from_spotify(
    mock_spotify: MagicMock,
    mock_discogs: MagicMock,
    mock_lastfm: MagicMock,
) -> None:
    """Resolver finds genre from Spotify artist genres (level 1)."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = "hardgroove"
    session.execute.return_value = mock_result

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await resolve_genre(
        track_id="track123",
        artist_name="ROD",
        track_name="Akephale",
        sp=mock_spotify,
        discogs=mock_discogs,
        lastfm=mock_lastfm,
        session_factory=factory,
    )

    assert result.has_match()
    assert result.genre_key == "hardgroove"
    assert result.source == "spotify"


@pytest.mark.asyncio
async def test_resolve_falls_through_to_manual(
    mock_spotify: MagicMock,
    mock_discogs: MagicMock,
    mock_lastfm: MagicMock,
) -> None:
    """Resolver returns manual when all levels fail to match."""
    # Make Spotify return no genres
    mock_spotify.artists.return_value = {"artists": [{"id": "a1", "genres": []}]}

    # Make Discogs return nothing
    empty_results = MagicMock()
    empty_results.count = 0
    empty_results.__getitem__ = MagicMock(side_effect=IndexError)
    mock_discogs.search.return_value = empty_results

    # Make Last.fm return nothing
    mock_lastfm.get_track.return_value.get_top_tags.return_value = []

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await resolve_genre(
        track_id="track_unknown",
        artist_name="Unknown Artist",
        track_name="Unknown Track",
        sp=mock_spotify,
        discogs=mock_discogs,
        lastfm=mock_lastfm,
        session_factory=factory,
    )

    assert not result.has_match()
    assert result.source == "manual"
