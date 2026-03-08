"""Tests for Telegram bot keyboards and notifications."""

import pytest

from src.bot.keyboards import (
    build_full_playlist_keyboard,
    build_genre_keyboard,
    build_reassign_keyboard,
)
from src.bot.notifications import _get_top_playlists
from src.db.models import GenrePlaylist, LikedTrack


def test_genre_keyboard_marks_suggested(sample_playlists: list[GenrePlaylist]) -> None:
    """Suggested genre gets ✨ marker in keyboard."""
    kb = build_genre_keyboard(
        track_db_id=1, playlists=sample_playlists, suggested_genre_key="hardgroove"
    )

    found = False
    for row in kb.inline_keyboard:
        for btn in row:
            if "Hardgroove" in btn.text and "✨" in btn.text:
                found = True
                assert btn.callback_data and btn.callback_data.startswith("a:1:")

    assert found, "Hardgroove button with ✨ not found"


def test_genre_keyboard_has_other_button(sample_playlists: list[GenrePlaylist]) -> None:
    """Keyboard includes 'Другой...' expand button."""
    kb = build_genre_keyboard(track_db_id=1, playlists=sample_playlists)

    last_row = kb.inline_keyboard[-1]
    assert len(last_row) == 1
    assert "Другой" in last_row[0].text
    assert last_row[0].callback_data == "e:1"


def test_full_playlist_keyboard(sample_playlists: list[GenrePlaylist]) -> None:
    """Full playlist keyboard shows all playlists."""
    kb = build_full_playlist_keyboard(track_db_id=1, playlists=sample_playlists)

    all_buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(all_buttons) == 4


def test_reassign_keyboard() -> None:
    """Reassign keyboard has single button."""
    kb = build_reassign_keyboard(track_db_id=42)

    assert len(kb.inline_keyboard) == 1
    assert kb.inline_keyboard[0][0].text == "↩️ Переназначить"
    assert kb.inline_keyboard[0][0].callback_data == "r:42"


def test_callback_data_within_64_bytes(sample_playlists: list[GenrePlaylist]) -> None:
    """All callback_data strings must be <= 64 bytes (Telegram limit)."""
    kb = build_genre_keyboard(
        track_db_id=999999, playlists=sample_playlists, suggested_genre_key="hardgroove"
    )
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data:
                assert len(btn.callback_data.encode()) <= 64, (
                    f"callback_data too long: {btn.callback_data!r}"
                )


def test_get_top_playlists_suggested_first(sample_playlists: list[GenrePlaylist]) -> None:
    """Suggested playlist appears first in top list."""
    top = _get_top_playlists(sample_playlists, "acid", limit=3)
    assert top[0].genre_key == "acid"
    assert len(top) == 3
