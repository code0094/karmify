"""Send new-like notifications to the Telegram chat."""

from aiogram import Bot

from src.bot.keyboards import build_full_playlist_keyboard, build_genre_keyboard
from src.db.models import GenrePlaylist, LikedTrack
from src.genre.resolver import GenreResult


async def send_new_like_notification(
    bot: Bot,
    chat_id: int,
    track: LikedTrack,
    genre_result: GenreResult,
    playlists: list[GenrePlaylist],
) -> int:
    """Send a notification about a new liked track. Returns the message ID."""
    lines = [
        f"🎵 Новый лайк от @{track.liked_by}",
        f"🎧 {track.artist_name} — {track.track_name}",
    ]

    if genre_result.label:
        lines.append(f"📀 Label: {genre_result.label}")

    if genre_result.has_match():
        lines.append(f"🏷 Detected: {genre_result.genre_key} (via {genre_result.source})")

    text = "\n".join(lines)

    if genre_result.has_match():
        # Show top playlists with the suggested one marked
        top_playlists = _get_top_playlists(playlists, genre_result.genre_key)
        keyboard = build_genre_keyboard(
            track.id, top_playlists, suggested_genre_key=genre_result.genre_key
        )
    else:
        # No genre detected — show full list
        keyboard = build_full_playlist_keyboard(track.id, playlists)

    msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
    return msg.message_id


def _get_top_playlists(
    playlists: list[GenrePlaylist], suggested_key: str | None, limit: int = 4
) -> list[GenrePlaylist]:
    """Get a short list of playlists: suggested first, then others up to limit."""
    if not suggested_key:
        return playlists[:limit]

    suggested = [p for p in playlists if p.genre_key == suggested_key]
    others = [p for p in playlists if p.genre_key != suggested_key]
    return (suggested + others)[:limit]
