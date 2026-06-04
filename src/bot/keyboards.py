"""Inline keyboard builders for Telegram bot.

Callback data format (max 64 bytes enforced by Telegram):
  a:{track_db_id}:{playlist_db_id}  — assign track to playlist
  e:{track_db_id}                   — expand full playlist list
  r:{track_db_id}                   — reassign (undo + pick new)
  d:{track_db_id}                   — download track audio (zotify)
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.db.models import GenrePlaylist


def _download_button(track_db_id: int, downloaded: bool = False) -> InlineKeyboardButton:
    """Build the download (⬇️) button row, reflecting whether it's already done."""
    text = "✅ Скачано" if downloaded else "⬇️ Скачать"
    return InlineKeyboardButton(text=text, callback_data=f"d:{track_db_id}")


def build_genre_keyboard(
    track_db_id: int,
    playlists: list[GenrePlaylist],
    suggested_genre_key: str | None = None,
    downloaded: bool = False,
) -> InlineKeyboardMarkup:
    """Build inline keyboard with genre playlist buttons.

    Args:
        track_db_id: DB primary key of the liked track.
        playlists: All available genre playlists.
        suggested_genre_key: The auto-detected genre (gets ✨ marker).
        downloaded: Whether the track's audio was already downloaded.
    """
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    for pl in playlists:
        label = f"{pl.emoji} {pl.display_name}"
        if pl.genre_key == suggested_genre_key:
            label += " ✨"

        callback_data = f"a:{track_db_id}:{pl.id}"
        row.append(InlineKeyboardButton(text=label, callback_data=callback_data))

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append(
        [
            InlineKeyboardButton(
                text="📋 Другой...",
                callback_data=f"e:{track_db_id}",
            )
        ]
    )
    buttons.append([_download_button(track_db_id, downloaded)])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_full_playlist_keyboard(
    track_db_id: int,
    playlists: list[GenrePlaylist],
    downloaded: bool = False,
) -> InlineKeyboardMarkup:
    """Build full playlist keyboard (when 'Другой...' is pressed or no genre detected)."""
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    for pl in playlists:
        label = f"{pl.emoji} {pl.display_name}"
        callback_data = f"a:{track_db_id}:{pl.id}"
        row.append(InlineKeyboardButton(text=label, callback_data=callback_data))

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([_download_button(track_db_id, downloaded)])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_reassign_keyboard(track_db_id: int, downloaded: bool = False) -> InlineKeyboardMarkup:
    """Reassign button plus the download button, shown after a track is assigned."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="↩️ Переназначить",
                    callback_data=f"r:{track_db_id}",
                )
            ],
            [_download_button(track_db_id, downloaded)],
        ]
    )
