"""Add tracks to Spotify playlists with deduplication."""

import asyncio

import spotipy
import structlog

logger = structlog.get_logger()


async def track_in_playlist(sp: spotipy.Spotify, playlist_id: str, track_id: str) -> bool:
    """Check if a track is already in a Spotify playlist."""
    offset = 0
    while True:
        results = await asyncio.to_thread(
            sp.playlist_tracks, playlist_id, offset=offset, limit=100, fields="items.track.id"
        )
        items = results.get("items", [])
        if not items:
            break
        for item in items:
            if item.get("track", {}).get("id") == track_id:
                return True
        offset += 100
    return False


async def add_track_to_playlist(
    sp: spotipy.Spotify, playlist_id: str, track_id: str
) -> bool:
    """Add a track to a playlist if not already present. Returns True if added."""
    if await track_in_playlist(sp, playlist_id, track_id):
        logger.info("playlist.track_already_exists", playlist=playlist_id, track=track_id)
        return False

    await asyncio.to_thread(sp.playlist_add_items, playlist_id, [track_id])
    logger.info("playlist.track_added", playlist=playlist_id, track=track_id)
    return True


async def remove_track_from_playlist(
    sp: spotipy.Spotify, playlist_id: str, track_id: str
) -> None:
    """Remove a track from a playlist."""
    await asyncio.to_thread(sp.playlist_remove_all_occurrences_of_items, playlist_id, [track_id])
    logger.info("playlist.track_removed", playlist=playlist_id, track=track_id)
