"""Tests for Spotify playlist ops: pagination, dedup, removal.

The spotipy client is mocked at its boundary (sp.playlist_tracks pages via
side_effect); internals of the module are never patched.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.spotify.playlist import (
    add_track_to_playlist,
    remove_track_from_playlist,
    track_in_playlist,
)


def _items(n: int, prefix: str = "x") -> list[dict]:
    return [{"track": {"id": f"{prefix}{i}"}} for i in range(n)]


def _offsets(sp: MagicMock) -> list[int]:
    return [c.kwargs["offset"] for c in sp.playlist_tracks.call_args_list]


@pytest.mark.asyncio
async def test_found_on_first_page_stops_paging() -> None:
    sp = MagicMock()
    sp.playlist_tracks.return_value = {"items": _items(3) + [{"track": {"id": "t1"}}]}

    assert await track_in_playlist(sp, "pl", "t1") is True
    assert _offsets(sp) == [0]


@pytest.mark.asyncio
async def test_found_on_second_page() -> None:
    sp = MagicMock()
    # 99 non-targets + 1 item without a "track" key (tolerated) = a full page.
    first_page = _items(99) + [{}]
    sp.playlist_tracks.side_effect = [
        {"items": first_page},
        {"items": [{"track": {"id": "t1"}}]},
    ]

    assert await track_in_playlist(sp, "pl", "t1") is True
    assert _offsets(sp) == [0, 100]


@pytest.mark.asyncio
async def test_empty_playlist_is_false() -> None:
    sp = MagicMock()
    sp.playlist_tracks.return_value = {"items": []}

    assert await track_in_playlist(sp, "pl", "t1") is False
    assert _offsets(sp) == [0]


@pytest.mark.asyncio
async def test_exactly_full_last_page_terminates() -> None:
    """A full page followed by an empty one: the loop must stop at False."""
    sp = MagicMock()
    sp.playlist_tracks.side_effect = [{"items": _items(100)}, {"items": []}]

    assert await track_in_playlist(sp, "pl", "t1") is False
    assert _offsets(sp) == [0, 100]


@pytest.mark.asyncio
async def test_null_track_items_are_skipped() -> None:
    """Regression: item['track']=None (deleted/unavailable Spotify tracks) used
    to crash track_in_playlist."""
    sp = MagicMock()
    sp.playlist_tracks.return_value = {"items": [{"track": None}, {"track": {"id": "t1"}}]}

    assert await track_in_playlist(sp, "pl", "t1") is True


@pytest.mark.asyncio
async def test_add_skips_duplicate() -> None:
    sp = MagicMock()
    sp.playlist_tracks.return_value = {"items": [{"track": {"id": "t1"}}]}

    assert await add_track_to_playlist(sp, "pl", "t1") is False
    sp.playlist_add_items.assert_not_called()


@pytest.mark.asyncio
async def test_add_when_absent() -> None:
    sp = MagicMock()
    sp.playlist_tracks.return_value = {"items": []}

    assert await add_track_to_playlist(sp, "pl", "t1") is True
    sp.playlist_add_items.assert_called_once_with("pl", ["t1"])


@pytest.mark.asyncio
async def test_remove_track() -> None:
    sp = MagicMock()

    await remove_track_from_playlist(sp, "pl", "t1")

    sp.playlist_remove_all_occurrences_of_items.assert_called_once_with("pl", ["t1"])
