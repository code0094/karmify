"""Unit tests for the three genre lookup modules (API clients mocked).

Client mocks are MagicMock, NOT AsyncMock: everything is called synchronously
inside asyncio.to_thread — an AsyncMock would hand the thread a coroutine.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pylast
import pytest
import spotipy

from src.genre.discogs_lookup import get_label, search_genre
from src.genre.lastfm_tags import get_top_tags
from src.genre.spotify_genres import get_artist_genres

# ---- spotify_genres -------------------------------------------------------


@pytest.mark.asyncio
async def test_spotify_collects_genres_from_all_artists_in_one_batch() -> None:
    sp = MagicMock()
    sp.track.return_value = {"artists": [{"id": "a1"}, {"id": "a2"}]}
    sp.artists.return_value = {
        "artists": [{"genres": ["hardgroove"]}, {"genres": ["techno", "acid"]}]
    }

    genres = await get_artist_genres(sp, "t1")

    assert genres == ["hardgroove", "techno", "acid"]
    sp.artists.assert_called_once_with(["a1", "a2"])  # one batched call — rate-limit friendly


@pytest.mark.asyncio
async def test_spotify_track_without_artists() -> None:
    sp = MagicMock()
    sp.track.return_value = {"artists": []}

    assert await get_artist_genres(sp, "t1") == []
    sp.artists.assert_not_called()


@pytest.mark.asyncio
async def test_spotify_exception_is_swallowed() -> None:
    sp = MagicMock()
    sp.track.side_effect = spotipy.SpotifyException(404, -1, "not found")

    assert await get_artist_genres(sp, "t1") == []


# ---- discogs_lookup -------------------------------------------------------


def _discogs_with_release(**attrs: object) -> MagicMock:
    release = MagicMock()
    for key, value in attrs.items():
        setattr(release, key, value)
    results = MagicMock()
    results.count = 1
    results.__getitem__ = MagicMock(return_value=release)
    client = MagicMock()
    client.search.return_value = results
    return client


@pytest.mark.asyncio
async def test_discogs_concatenates_genres_then_styles() -> None:
    client = _discogs_with_release(genres=["Electronic"], styles=["Hardgroove", "Techno"])

    tags = await search_genre(client, "ROD", "Akephale")

    assert tags == ["Electronic", "Hardgroove", "Techno"]


@pytest.mark.asyncio
async def test_discogs_empty_results() -> None:
    client = MagicMock()
    client.search.return_value.count = 0

    assert await search_genre(client, "ROD", "Akephale") == []


@pytest.mark.asyncio
async def test_discogs_none_genre_fields() -> None:
    client = _discogs_with_release(genres=None, styles=None)

    assert await search_genre(client, "ROD", "Akephale") == []


@pytest.mark.asyncio
async def test_discogs_exception_is_swallowed() -> None:
    client = MagicMock()
    client.search.side_effect = RuntimeError("api down")

    assert await search_genre(client, "ROD", "Akephale") == []


@pytest.mark.asyncio
async def test_get_label_returns_real_string(mock_discogs: MagicMock) -> None:
    # Uses the shared fixture: proves it yields the actual string, not a mock repr.
    assert await get_label(mock_discogs, "ROD", "Akephale") == "Planet Rhythm"


@pytest.mark.asyncio
async def test_get_label_no_labels_and_exception() -> None:
    assert await get_label(_discogs_with_release(labels=[]), "ROD", "Akephale") is None

    broken = MagicMock()
    broken.search.side_effect = RuntimeError("api down")
    assert await get_label(broken, "ROD", "Akephale") is None


# ---- lastfm_tags ----------------------------------------------------------


def _tag(name: str, weight: str) -> MagicMock:
    tag = MagicMock()
    tag.item.get_name.return_value = name
    tag.weight = weight
    return tag


@pytest.mark.asyncio
async def test_lastfm_weight_filter_on_string_weights() -> None:
    """pylast delivers weights as strings; > 30 strictly (30 itself is dropped)."""
    network = MagicMock()
    network.get_track.return_value.get_top_tags.return_value = [
        _tag("techno", "31"),
        _tag("noise", "30"),
    ]

    assert await get_top_tags(network, "ROD", "Akephale") == ["techno"]


@pytest.mark.asyncio
async def test_lastfm_wserror_is_swallowed() -> None:
    network = MagicMock()
    network.get_track.side_effect = pylast.WSError(None, None, "Track not found")

    assert await get_top_tags(network, "ROD", "Akephale") == []


@pytest.mark.asyncio
async def test_lastfm_other_exception_is_swallowed() -> None:
    network = MagicMock()
    network.get_track.side_effect = RuntimeError("api down")

    assert await get_top_tags(network, "ROD", "Akephale") == []
