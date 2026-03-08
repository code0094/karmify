"""Inline button callback handlers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery

from src.bot.keyboards import build_full_playlist_keyboard, build_reassign_keyboard
from src.db import repos
from src.spotify import playlist as spotify_playlist

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.spotify.client import SpotifyClient

logger = structlog.get_logger()
router = Router()


def setup_callback_router(
    session_factory: async_sessionmaker[AsyncSession],
    spotify_clients: dict[str, SpotifyClient],
) -> Router:
    """Create and return a router with callback handlers wired to dependencies."""

    @router.callback_query(F.data.startswith("assign:"))
    async def handle_assign(callback: CallbackQuery) -> None:
        """Handle playlist assignment button press."""
        if not callback.data or not callback.from_user:
            return

        parts = callback.data.split(":")
        track_db_id = int(parts[1])
        playlist_id = parts[2]
        genre_key = parts[3]

        async with session_factory() as session:
            # Lock the row to prevent concurrent assignment
            track = await repos.get_track_for_update(session, track_db_id)

            if not track:
                await callback.answer("Трек не найден", show_alert=True)
                return

            if track.assigned_playlist_id:
                await callback.answer("Трек уже назначен в плейлист", show_alert=True)
                return

            client = spotify_clients.get(track.liked_by)
            if not client:
                await callback.answer("Spotify client не найден", show_alert=True)
                return

            sp = await client.get_client()
            added = await spotify_playlist.add_track_to_playlist(
                sp, playlist_id, track.spotify_track_id
            )
            if not added:
                await callback.answer("Трек уже в этом плейлисте", show_alert=True)
                return

            assigned_by = callback.from_user.username or str(callback.from_user.id)
            await repos.assign_track_to_playlist(
                session,
                track_db_id,
                playlist_id,
                assigned_by,
                callback.message.message_id if callback.message else None,
            )

        await callback.answer(f"✅ Добавлено в {genre_key}!")

        if callback.message:
            await callback.message.edit_reply_markup(
                reply_markup=build_reassign_keyboard(track_db_id)
            )

        logger.info(
            "track.assigned",
            track_id=track.spotify_track_id,
            playlist=playlist_id,
            genre=genre_key,
            by=assigned_by,
        )

    @router.callback_query(F.data.startswith("reassign:"))
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

            # Clear assignment in DB (NULL, not empty strings)
            await repos.assign_track_to_playlist(session, track_db_id, None, None, None)

            playlists = await repos.get_all_playlists(session)

        # Remove from Spotify playlist (outside DB transaction)
        client = spotify_clients.get(old_liked_by)
        if client:
            sp = await client.get_client()
            await spotify_playlist.remove_track_from_playlist(sp, old_playlist_id, old_track_id)

        if callback.message:
            await callback.message.edit_reply_markup(
                reply_markup=build_full_playlist_keyboard(track_db_id, playlists)
            )

        await callback.answer("Выбери новый плейлист")

    @router.callback_query(F.data.startswith("expand:"))
    async def handle_expand(callback: CallbackQuery) -> None:
        """Expand to show full playlist list."""
        if not callback.data:
            return

        track_db_id = int(callback.data.split(":")[1])

        async with session_factory() as session:
            playlists = await repos.get_all_playlists(session)

        if callback.message:
            await callback.message.edit_reply_markup(
                reply_markup=build_full_playlist_keyboard(track_db_id, playlists)
            )

        await callback.answer()

    return router
