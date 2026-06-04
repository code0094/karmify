"""Entrypoint: start the Telegram bot.

Likes are fetched on demand via the /fetch command (manual "thick client" mode) —
there is no scheduled poller. Track audio is downloaded on demand via the ⬇️ button.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from functools import partial

import discogs_client
import pylast
import structlog
from sqlalchemy import update

from src.bot.app import create_bot, create_dispatcher
from src.bot.notifications import send_new_like_notification
from src.config import get_settings
from src.db import repos
from src.db.engine import build_engine
from src.db.models import LikedTrack
from src.genre.resolver import GenreResult, resolve_genre
from src.spotify.client import SpotifyClient
from src.spotify.downloader import TrackDownloader
from src.spotify.poller import poll_all_users
from src.utils.logging import setup_logging

logger = structlog.get_logger()


async def main() -> None:
    """Application entrypoint."""
    settings = get_settings()
    setup_logging(settings.log_level)

    # Database
    engine, session_factory = build_engine(settings)

    # Spotify clients
    karma_client = SpotifyClient("karma", settings, session_factory)
    stress303_client = SpotifyClient("stress303", settings, session_factory)
    spotify_clients = {"karma": karma_client, "stress303": stress303_client}
    all_clients = [karma_client, stress303_client]

    # External APIs
    discogs = discogs_client.Client("AuxDJBot/0.1", user_token=settings.discogs_user_token)
    lastfm = pylast.LastFMNetwork(
        api_key=settings.lastfm_api_key, api_secret=settings.lastfm_api_secret
    )

    # On-demand track audio downloader (zotify)
    downloader = TrackDownloader(settings)

    # Telegram bot
    bot = create_bot(settings.telegram_bot_token)

    async def on_new_track(track: LikedTrack) -> None:
        """Process a newly detected liked track: resolve genre and notify."""
        sp = await spotify_clients[track.liked_by].get_client()

        genre_result: GenreResult = await resolve_genre(
            track_id=track.spotify_track_id,
            artist_name=track.artist_name or "",
            track_name=track.track_name or "",
            sp=sp,
            discogs=discogs,
            lastfm=lastfm,
            session_factory=session_factory,
        )

        # Update track in DB with genre info
        async with session_factory() as session:
            await session.execute(
                update(LikedTrack)
                .where(LikedTrack.id == track.id)
                .values(detected_genre=genre_result.genre_key, genre_source=genre_result.source)
            )
            await session.commit()

            playlists = await repos.get_all_playlists(session)

        msg_id = await send_new_like_notification(
            bot, settings.telegram_chat_id, track, genre_result, playlists
        )

        logger.info(
            "track.notified",
            track=track.track_name,
            artist=track.artist_name,
            genre=genre_result.genre_key,
            source=genre_result.source,
            message_id=msg_id,
        )

    # Manual fetch (replaces the scheduled watchdog): one poll pass over all users.
    fetch_likes = partial(poll_all_users, all_clients, session_factory, on_new_track)

    dp = create_dispatcher(session_factory, spotify_clients, downloader, settings, fetch_likes)

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("shutdown.signal_received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Windows ProactorEventLoop has no add_signal_handler; we rely on the
        # KeyboardInterrupt fallback below instead.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _signal_handler)

    # Start polling for Telegram updates
    polling_task = asyncio.create_task(dp.start_polling(bot))

    # Wait for shutdown signal (or Ctrl+C on platforms without signal handlers)
    try:
        await shutdown_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("shutdown.interrupted")
    finally:
        logger.info("shutdown.stopping")
        polling_task.cancel()
        await bot.session.close()
        await engine.dispose()
        logger.info("shutdown.done")


if __name__ == "__main__":
    asyncio.run(main())
