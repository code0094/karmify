"""Spotify liked tracks poller — runs on schedule (08:00 / 20:00 UTC)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db import repos
from src.db.models import LikedTrack
from src.spotify.client import SpotifyClient

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from typing import Any

logger = structlog.get_logger()


async def poll_user_likes(
    spotify_client: SpotifyClient,
    session_factory: async_sessionmaker[AsyncSession],
    on_new_track: Callable[[LikedTrack], Coroutine[Any, Any, None]],
) -> None:
    """Fetch recent likes for one user, insert new ones, and call on_new_track callback."""
    sp = await spotify_client.get_client()
    user_label = spotify_client.user_label

    async with session_factory() as session:
        last_liked_at = await repos.get_last_liked_at(session, user_label)

    logger.info("poller.start", user=user_label, last_liked_at=last_liked_at)

    offset = 0
    new_count = 0

    while True:
        results = await asyncio.to_thread(sp.current_user_saved_tracks, limit=50, offset=offset)
        items = results.get("items", [])
        if not items:
            break

        stop = False
        for item in items:
            added_at_str: str = item["added_at"]
            added_at = datetime.fromisoformat(added_at_str.replace("Z", "+00:00"))

            if last_liked_at and added_at <= last_liked_at:
                stop = True
                break

            track_data = item["track"]
            track = LikedTrack(
                spotify_track_id=track_data["id"],
                track_name=track_data["name"],
                artist_name=", ".join(a["name"] for a in track_data["artists"]),
                liked_by=user_label,
                liked_at=added_at,
            )

            async with session_factory() as session:
                exists = await repos.track_exists(session, track.spotify_track_id, user_label)
                if exists:
                    continue
                track = await repos.insert_liked_track(session, track)

            new_count += 1
            await on_new_track(track)

        if stop or len(items) < 50:
            break
        offset += 50

    logger.info("poller.done", user=user_label, new_tracks=new_count)


async def poll_all_users(
    clients: list[SpotifyClient],
    session_factory: async_sessionmaker[AsyncSession],
    on_new_track: Callable[[LikedTrack], Coroutine[Any, Any, None]],
) -> None:
    """Poll likes for all configured users."""
    for client in clients:
        try:
            await poll_user_likes(client, session_factory, on_new_track)
        except Exception:
            logger.exception("poller.error", user=client.user_label)
