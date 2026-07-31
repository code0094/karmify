"""Tests for the new-like Telegram notification."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from aiogram.types import InlineKeyboardMarkup

from src.bot.notifications import send_new_like_notification
from src.db.models import GenrePlaylist, LikedTrack
from src.genre.resolver import GenreResult


def _bot() -> AsyncMock:
    bot = AsyncMock()
    bot.send_message.return_value = MagicMock(message_id=42)
    return bot


def _track() -> LikedTrack:
    return LikedTrack(
        id=7, spotify_track_id="t1", track_name="Akephale", artist_name="ROD", liked_by="karma"
    )


def _buttons(markup: InlineKeyboardMarkup) -> list[str]:
    return [btn.text for row in markup.inline_keyboard for btn in row]


async def test_notification_with_match(sample_playlists: list[GenrePlaylist]) -> None:
    bot = _bot()
    result = GenreResult(
        genre_key="hardgroove", raw_genre="hardgroove", source="discogs", label="Planet Rhythm"
    )

    message_id = await send_new_like_notification(bot, -100123, _track(), result, sample_playlists)

    assert message_id == 42
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == -100123
    text = kwargs["text"]
    assert "Новый лайк от @karma" in text
    assert "ROD — Akephale" in text
    assert "Label: Planet Rhythm" in text
    assert "Detected: hardgroove (via discogs)" in text
    buttons = _buttons(kwargs["reply_markup"])
    assert any("✨" in b and "Hardgroove" in b for b in buttons)  # suggested marked
    assert any("Другой" in b for b in buttons)  # genre keyboard, not the full list


async def test_notification_without_match(sample_playlists: list[GenrePlaylist]) -> None:
    bot = _bot()
    result = GenreResult(genre_key=None, raw_genre=None, source="manual", label=None)

    await send_new_like_notification(bot, -100123, _track(), result, sample_playlists)

    kwargs = bot.send_message.await_args.kwargs
    text = kwargs["text"]
    assert "Label:" not in text
    assert "Detected:" not in text
    buttons = _buttons(kwargs["reply_markup"])
    assert not any("Другой" in b for b in buttons)  # full list — no expand button
    assert sum(1 for b in buttons if "✨" in b) == 0
