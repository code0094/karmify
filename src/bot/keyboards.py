"""Inline keyboard builders for Telegram bot."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.db.models import GenrePlaylist


def build_genre_keyboard(
    track_db_id: int,
    playlists: list[GenrePlaylist],
    suggested_genre_key: str | None = None,
) -> InlineKeyboardMarkup:
    """Build inline keyboard with genre playlist buttons.

    Args:
        track_db_id: DB primary key of the liked track.
        playlists: All available genre playlists.
        suggested_genre_key: The auto-detected genre (gets ✨ marker).
    """
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    for pl in playlists:
        label = f"{pl.emoji} {pl.display_name}"
        if pl.genre_key == suggested_genre_key:
            label += " ✨"

        callback_data = f"assign:{track_db_id}:{pl.playlist_id}:{pl.genre_key}"
        row.append(InlineKeyboardButton(text=label, callback_data=callback_data))

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    # "Другой..." button that expands full list (handled same way — all are shown)
    buttons.append([
        InlineKeyboardButton(
            text="📋 Другой...",
            callback_data=f"expand:{track_db_id}",
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_full_playlist_keyboard(
    track_db_id: int,
    playlists: list[GenrePlaylist],
) -> InlineKeyboardMarkup:
    """Build full playlist keyboard (when 'Другой...' is pressed or no genre detected)."""
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    for pl in playlists:
        label = f"{pl.emoji} {pl.display_name}"
        callback_data = f"assign:{track_db_id}:{pl.playlist_id}:{pl.genre_key}"
        row.append(InlineKeyboardButton(text=label, callback_data=callback_data))

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_reassign_keyboard(track_db_id: int) -> InlineKeyboardMarkup:
    """Single button to reassign a track to a different playlist."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="↩️ Переназначить",
                    callback_data=f"reassign:{track_db_id}",
                )
            ]
        ]
    )
