"""Tests for Spotify poller."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.spotify.poller import poll_user_likes


@pytest.mark.asyncio
async def test_poller_detects_new_tracks() -> None:
    """Poller calls on_new_track for new liked tracks."""
    # Mock SpotifyClient
    sp = MagicMock()
    sp.current_user_saved_tracks.return_value = {
        "items": [
            {
                "added_at": "2026-03-08T12:00:00Z",
                "track": {
                    "id": "new_track_1",
                    "name": "Test Track",
                    "artists": [{"name": "Test Artist"}],
                },
            }
        ]
    }

    client = AsyncMock()
    client.user_label = "karma"
    client.get_client = AsyncMock(return_value=sp)

    # Mock session factory + repos
    session = AsyncMock()

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)

    on_new_track = AsyncMock()

    with (
        patch("src.spotify.poller.repos.get_last_liked_at", return_value=None),
        patch("src.spotify.poller.repos.track_exists", return_value=False),
        patch("src.spotify.poller.repos.insert_liked_track", side_effect=lambda s, t: t),
    ):
        await poll_user_likes(client, factory, on_new_track)

    on_new_track.assert_called_once()


@pytest.mark.asyncio
async def test_poller_skips_existing_tracks() -> None:
    """Poller does not call on_new_track for tracks already in DB."""
    sp = MagicMock()
    sp.current_user_saved_tracks.return_value = {
        "items": [
            {
                "added_at": "2026-03-08T12:00:00Z",
                "track": {
                    "id": "existing_track",
                    "name": "Old Track",
                    "artists": [{"name": "Old Artist"}],
                },
            }
        ]
    }

    client = AsyncMock()
    client.user_label = "karma"
    client.get_client = AsyncMock(return_value=sp)

    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)

    on_new_track = AsyncMock()

    with (
        patch("src.spotify.poller.repos.get_last_liked_at", return_value=None),
        patch("src.spotify.poller.repos.track_exists", return_value=True),
    ):
        await poll_user_likes(client, factory, on_new_track)

    on_new_track.assert_not_called()


@pytest.mark.asyncio
async def test_poller_skips_null_track_items() -> None:
    """Spotify returns "track": null for deleted/unavailable liked tracks.

    Crashing here would be silently swallowed by poll_all_users while
    last_liked_at never advances — every older like would stop syncing.
    """
    sp = MagicMock()
    sp.current_user_saved_tracks.return_value = {
        "items": [
            {"added_at": "2026-03-08T12:00:00Z", "track": None},
            {
                "added_at": "2026-03-08T11:00:00Z",
                "track": {"id": "ok", "name": "Real", "artists": [{"name": "ROD"}]},
            },
        ]
    }

    client = AsyncMock()
    client.user_label = "karma"
    client.get_client = AsyncMock(return_value=sp)

    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)

    on_new_track = AsyncMock()

    with (
        patch("src.spotify.poller.repos.get_last_liked_at", return_value=None),
        patch("src.spotify.poller.repos.track_exists", return_value=False),
        patch("src.spotify.poller.repos.insert_liked_track", side_effect=lambda s, t: t),
    ):
        new_count = await poll_user_likes(client, factory, on_new_track)

    assert new_count == 1
    assert on_new_track.await_args.args[0].spotify_track_id == "ok"
