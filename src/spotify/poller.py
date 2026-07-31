"""Spotify liked tracks poller — runs on schedule (08:00 / 20:00 UTC)."""

from __future__ import annotations

import asyncio
from datetime import datetime
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
) -> int:
    """Fetch recent likes for one user, insert new ones, call on_new_track.

    Returns:
        The number of genuinely new tracks processed.
    """
    sp = await spotify_client.get_client()
    user_label = spotify_client.user_label

    async with session_factory() as session:
        last_liked_at = await repos.get_last_liked_at(session, user_label)

    logger.info("poller.start", user=user_label, last_liked_at=last_liked_at)

    # Collect first, store second. Spotify returns likes newest-first, and
    # last_liked_at is a high-water mark: committing a newer track before an
    # older one succeeds would push the mark past the older one, hiding it from
    # every later poll. Inserting oldest-first keeps the mark honest.
    pending: list[LikedTrack] = []
    offset = 0

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

            # Spotify sends "track": null for deleted/unavailable liked tracks.
            track_data = item.get("track")
            if not track_data:
                logger.info("poller.null_track_skipped", user=user_label, added_at=added_at_str)
                continue

            pending.append(
                LikedTrack(
                    spotify_track_id=track_data["id"],
                    track_name=track_data["name"],
                    artist_name=", ".join(a["name"] for a in track_data["artists"]),
                    liked_by=user_label,
                    liked_at=added_at,
                )
            )

        if stop or len(items) < 50:
            break
        offset += 50

    new_count = 0
    for track in reversed(pending):  # oldest first
        try:
            async with session_factory() as session:
                if await repos.track_exists(session, track.spotify_track_id, user_label):
                    continue
                stored = await repos.insert_liked_track(session, track)
        except Exception:
            # A failed insert (e.g. the bot and the sidecar polling the same DB)
            # must not carry the cursor past this track — stop the pass here and
            # retry it next time.
            logger.exception("poller.insert_failed", user=user_label, track=track.spotify_track_id)
            break

        new_count += 1
        # The row is committed, so track_exists() skips it on every later poll:
        # a failure here would silently cost it its genre and notification.
        try:
            await on_new_track(stored)
        except Exception:
            logger.exception(
                "poller.on_new_track_failed", user=user_label, track=track.spotify_track_id
            )

    logger.info("poller.done", user=user_label, new_tracks=new_count)
    return new_count


async def poll_all_users(
    clients: list[SpotifyClient],
    session_factory: async_sessionmaker[AsyncSession],
    on_new_track: Callable[[LikedTrack], Coroutine[Any, Any, None]],
) -> int:
    """Poll likes for all configured users. Returns total new tracks processed."""
    total = 0
    for client in clients:
        try:
            total += await poll_user_likes(client, session_factory, on_new_track)
        except Exception:
            logger.exception("poller.error", user=client.user_label)
    return total
