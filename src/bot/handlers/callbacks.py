"""Inline button callback handlers.

Callback data format:
  a:{track_db_id}:{playlist_db_id}  — assign
  e:{track_db_id}                   — expand
  r:{track_db_id}                   — reassign
  d:{track_db_id}                   — download track audio (zotify)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, FSInputFile, Message

from src.bot.keyboards import build_full_playlist_keyboard, build_reassign_keyboard
from src.db import repos
from src.spotify import playlist as spotify_playlist
from src.spotify.downloader import DownloadError

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.config import Settings
    from src.spotify.client import SpotifyClient
    from src.spotify.downloader import TrackDownloader

logger = structlog.get_logger()
router = Router()

# Background download tasks. The event loop only keeps weak references to tasks,
# so an unreferenced one can be garbage-collected mid-download.
_background_tasks: set[asyncio.Task[None]] = set()


def _spawn(coro: Coroutine[Any, Any, None]) -> None:
    """Run a coroutine in the background, keeping a strong reference to it."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _editable(callback: CallbackQuery) -> Message | None:
    """The callback's message when it is still accessible (old ones are not)."""
    return callback.message if isinstance(callback.message, Message) else None


def setup_callback_router(
    session_factory: async_sessionmaker[AsyncSession],
    spotify_clients: dict[str, SpotifyClient],
    downloader: TrackDownloader,
    settings: Settings,
) -> Router:
    """Create and return a router with callback handlers wired to dependencies."""

    @router.callback_query(F.data.startswith("a:"))
    async def handle_assign(callback: CallbackQuery) -> None:
        """Handle playlist assignment button press."""
        if not callback.data or not callback.from_user:
            return

        parts = callback.data.split(":")
        track_db_id = int(parts[1])
        playlist_db_id = int(parts[2])

        async with session_factory() as session:
            track = await repos.get_track_for_update(session, track_db_id)

            if not track:
                await callback.answer("Трек не найден", show_alert=True)
                return

            if track.assigned_playlist_id:
                await callback.answer("Трек уже назначен в плейлист", show_alert=True)
                return

            # Resolve playlist from DB ID
            playlist = await repos.get_playlist_by_id(session, playlist_db_id)
            if not playlist:
                await callback.answer("Плейлист не найден", show_alert=True)
                return

            client = spotify_clients.get(track.liked_by)
            if not client:
                await callback.answer("Spotify client не найден", show_alert=True)
                return

            sp = await client.get_client()
            added = await spotify_playlist.add_track_to_playlist(
                sp, playlist.playlist_id, track.spotify_track_id
            )
            if not added:
                await callback.answer("Трек уже в этом плейлисте", show_alert=True)
                return

            assigned_by = callback.from_user.username or str(callback.from_user.id)
            await repos.assign_track_to_playlist(
                session,
                track_db_id,
                playlist.playlist_id,
                assigned_by,
                message.message_id if (message := _editable(callback)) else None,
            )

        await callback.answer(f"✅ Добавлено в {playlist.display_name}!")

        if message := _editable(callback):
            await message.edit_reply_markup(
                reply_markup=build_reassign_keyboard(
                    track_db_id, downloaded=track.downloaded_at is not None
                )
            )

        logger.info(
            "track.assigned",
            track_id=track.spotify_track_id,
            playlist=playlist.playlist_id,
            genre=playlist.genre_key,
            by=assigned_by,
        )

    @router.callback_query(F.data.startswith("r:"))
    async def handle_reassign(callback: CallbackQuery) -> None:
        """Handle reassign button — remove from current playlist, show full list."""
        if not callback.data:
            return

        track_db_id = int(callback.data.split(":")[1])

        async with session_factory() as session:
            track = await repos.get_track_for_update(session, track_db_id)

            if not track or not track.assigned_playlist_id:
                await callback.answer("Нечего переназначать", show_alert=True)
                return

            if track.assigned_at:
                deadline = track.assigned_at + timedelta(hours=24)
                if datetime.now(tz=UTC) > deadline:
                    await callback.answer(
                        "Прошло больше 24ч, переназначение недоступно", show_alert=True
                    )
                    return

            old_playlist_id = track.assigned_playlist_id
            old_track_id = track.spotify_track_id
            old_liked_by = track.liked_by

            await repos.assign_track_to_playlist(session, track_db_id, None, None, None)
            playlists = await repos.get_all_playlists(session)

        downloaded = track.downloaded_at is not None
        client = spotify_clients.get(old_liked_by)
        if client:
            sp = await client.get_client()
            await spotify_playlist.remove_track_from_playlist(sp, old_playlist_id, old_track_id)

        if message := _editable(callback):
            await message.edit_reply_markup(
                reply_markup=build_full_playlist_keyboard(
                    track_db_id, playlists, downloaded=downloaded
                )
            )

        await callback.answer("Выбери новый плейлист")

    @router.callback_query(F.data.startswith("e:"))
    async def handle_expand(callback: CallbackQuery) -> None:
        """Expand to show full playlist list."""
        if not callback.data:
            return

        track_db_id = int(callback.data.split(":")[1])

        async with session_factory() as session:
            playlists = await repos.get_all_playlists(session)
            track = await repos.get_track_by_id(session, track_db_id)

        downloaded = bool(track and track.downloaded_at)
        if message := _editable(callback):
            await message.edit_reply_markup(
                reply_markup=build_full_playlist_keyboard(
                    track_db_id, playlists, downloaded=downloaded
                )
            )

        await callback.answer()

    @router.callback_query(F.data.startswith("d:"))
    async def handle_download(callback: CallbackQuery) -> None:
        """Handle the download (⬇️) button — fetch audio via zotify in the background."""
        if not callback.data:
            return

        track_db_id = int(callback.data.split(":")[1])

        async with session_factory() as session:
            track = await repos.get_track_by_id(session, track_db_id)

        if not track:
            await callback.answer("Трек не найден", show_alert=True)
            return
        if track.downloaded_at:
            await callback.answer("Трек уже скачан", show_alert=True)
            return

        # Downloading takes far longer than Telegram's ~15s callback window, so
        # ack immediately and run the actual download in a background task.
        await callback.answer("⏳ Скачиваю, это займёт время…")
        _spawn(_run_download(callback, track_db_id, track.spotify_track_id))

    async def _run_download(
        callback: CallbackQuery, track_db_id: int, spotify_track_id: str
    ) -> None:
        try:
            path = await downloader.download(spotify_track_id)
        except DownloadError as exc:
            logger.warning("download.error", track=spotify_track_id, error=str(exc))
            if message := _editable(callback):
                await message.reply(f"❌ Не удалось скачать: {exc}")
            return
        except Exception:
            logger.exception("download.unexpected", track=spotify_track_id)
            if message := _editable(callback):
                await message.reply("❌ Не удалось скачать: внутренняя ошибка")
            return

        async with session_factory() as session:
            await repos.mark_track_downloaded(session, track_db_id, str(path))
            fresh = await repos.get_track_by_id(session, track_db_id)
            playlists = await repos.get_all_playlists(session)

        size_mb = path.stat().st_size / (1024 * 1024)
        message = _editable(callback)
        if settings.download_send_to_chat and message:
            if size_mb <= settings.telegram_upload_limit_mb:
                await message.answer_audio(FSInputFile(path))
            else:
                await message.reply(
                    f"✅ Скачано в библиотеку ({size_mb:.0f} МБ — велик для Telegram):\n{path}"
                )

        # Refresh the keyboard to mark the track as downloaded.
        if message:
            if fresh and fresh.assigned_playlist_id:
                keyboard = build_reassign_keyboard(track_db_id, downloaded=True)
            else:
                keyboard = build_full_playlist_keyboard(track_db_id, playlists, downloaded=True)
            try:
                await message.edit_reply_markup(reply_markup=keyboard)
            except TelegramBadRequest:
                logger.debug("download.markup_unchanged", track=spotify_track_id)

        logger.info("download.delivered", track=spotify_track_id, size_mb=round(size_mb, 1))

    return router
