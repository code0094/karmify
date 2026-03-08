"""Entrypoint: start Telegram bot + scheduled Spotify poller."""

from __future__ import annotations

import asyncio
import signal
from functools import partial

import discogs_client
import pylast
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.bot.app import create_bot, create_dispatcher
from src.bot.notifications import send_new_like_notification
from src.config import get_settings
from src.db import repos
from src.db.engine import build_engine
from src.db.models import LikedTrack
from src.genre.resolver import GenreResult, resolve_genre
from src.spotify.client import SpotifyClient
from src.spotify.poller import poll_all_users
from src.utils.logging import setup_logging

logger = structlog.get_logger()


async def main() -> None:
    """Application entrypoint."""
    settings = get_settings()
    setup_logging(settings.log_level)

    # Database
    session_factory = build_engine(settings)

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

    # Telegram bot
    bot = create_bot(settings.telegram_bot_token)
    dp = create_dispatcher(session_factory, spotify_clients)

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
            from sqlalchemy import update

            from src.db.models import LikedTrack as LT

            await session.execute(
                update(LT)
                .where(LT.id == track.id)
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

    # Scheduler for polling
    scheduler = AsyncIOScheduler()
    poll_job = partial(poll_all_users, all_clients, session_factory, on_new_track)

    for hour, minute in settings.poll_times():
        scheduler.add_job(
            poll_job,
            CronTrigger(hour=hour, minute=minute),
            id=f"poll_{hour:02d}_{minute:02d}",
            replace_existing=True,
        )
        logger.info("scheduler.job_added", time=f"{hour:02d}:{minute:02d}")

    scheduler.start()

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("shutdown.signal_received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    # Start polling for Telegram updates
    polling_task = asyncio.create_task(dp.start_polling(bot))

    # Wait for shutdown signal
    await shutdown_event.wait()

    logger.info("shutdown.stopping")
    scheduler.shutdown(wait=False)
    await bot.session.close()
    polling_task.cancel()
    logger.info("shutdown.done")


if __name__ == "__main__":
    asyncio.run(main())
