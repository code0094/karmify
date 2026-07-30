"""Tests for the download (⬇️) callback and its background delivery task.

Only this flow is covered here; the assign/reassign callbacks are still on the
backlog (see notes/test-catalog.md).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import src.bot.handlers.callbacks as callbacks_mod
from src.bot.handlers.callbacks import setup_callback_router
from src.config import Settings
from src.db import repos
from src.db.models import LikedTrack

Factory = async_sessionmaker[AsyncSession]


def _get_handler(name: str) -> Callable[..., object]:
    """Last registered handler by name (setup_* stacks onto a module router)."""
    handlers = [
        h.callback
        for h in callbacks_mod.router.callback_query.handlers
        if h.callback.__name__ == name
    ]
    assert handlers, f"handler {name} not registered"
    return handlers[-1]


def _callback(track_db_id: int) -> MagicMock:
    callback = MagicMock()
    callback.data = f"d:{track_db_id}"
    callback.answer = AsyncMock()
    # A real aiogram Message so _editable() does not filter it out.
    message = MagicMock(spec=callbacks_mod.Message)
    message.answer_audio = AsyncMock()
    message.reply = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    callback.message = message
    return callback


async def _drain_background_tasks() -> None:
    while callbacks_mod._background_tasks:
        await asyncio.gather(*callbacks_mod._background_tasks, return_exceptions=True)


@pytest.fixture
async def track(db_session_factory: Factory) -> LikedTrack:
    async with db_session_factory() as session:
        return await repos.insert_liked_track(
            session,
            LikedTrack(spotify_track_id="t1", track_name="Akephale", liked_by="karma"),
        )


def _settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(download_send_to_chat=True, telegram_upload_limit_mb=50)


async def test_download_delivers_audio_and_marks_track(
    db_session_factory: Factory,
    track: LikedTrack,
    make_settings: Callable[..., Settings],
    tmp_path: Path,
) -> None:
    audio = tmp_path / "akephale.mp3"
    audio.write_bytes(b"x" * 1024)
    downloader = MagicMock()
    downloader.download = AsyncMock(return_value=audio)

    setup_callback_router(db_session_factory, {}, downloader, _settings(make_settings))
    callback = _callback(track.id)

    await _get_handler("handle_download")(callback)
    await _drain_background_tasks()

    callback.message.answer_audio.assert_awaited_once()
    async with db_session_factory() as session:
        stored = await repos.get_track_by_id(session, track.id)
    assert stored is not None
    assert stored.downloaded_at is not None
    assert stored.download_path == str(audio)


async def test_delivery_failure_is_reported_not_swallowed(
    db_session_factory: Factory,
    track: LikedTrack,
    make_settings: Callable[..., Settings],
    tmp_path: Path,
) -> None:
    """A background task's error reaches nobody by default — it must be logged
    and reported instead of vanishing."""
    audio = tmp_path / "akephale.mp3"
    audio.write_bytes(b"x" * 1024)
    downloader = MagicMock()
    downloader.download = AsyncMock(return_value=audio)

    setup_callback_router(db_session_factory, {}, downloader, _settings(make_settings))
    callback = _callback(track.id)
    callback.message.answer_audio = AsyncMock(side_effect=RuntimeError("flood control"))

    await _get_handler("handle_download")(callback)
    await _drain_background_tasks()

    callback.message.reply.assert_awaited_once()
    assert "не доставлено" in callback.message.reply.await_args.args[0]


async def test_already_downloaded_track_is_rejected(
    db_session_factory: Factory,
    track: LikedTrack,
    make_settings: Callable[..., Settings],
) -> None:
    async with db_session_factory() as session:
        await repos.mark_track_downloaded(session, track.id, "somewhere.mp3")

    downloader = MagicMock()
    downloader.download = AsyncMock()
    setup_callback_router(db_session_factory, {}, downloader, _settings(make_settings))
    callback = _callback(track.id)

    await _get_handler("handle_download")(callback)

    downloader.download.assert_not_awaited()
    assert callback.answer.await_args.kwargs.get("show_alert") is True
