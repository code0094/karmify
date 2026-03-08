"""Fetch artist genres from Spotify API."""

import spotipy
import structlog

logger = structlog.get_logger()


async def get_artist_genres(sp: spotipy.Spotify, track_id: str) -> list[str]:
    """Get genre tags from the track's artists via Spotify."""
    try:
        track = sp.track(track_id)
        artist_ids = [a["id"] for a in track.get("artists", [])]
        if not artist_ids:
            return []

        artists = sp.artists(artist_ids)
        genres: list[str] = []
        for artist in artists.get("artists", []):
            genres.extend(artist.get("genres", []))

        logger.debug("spotify_genres.result", track_id=track_id, genres=genres)
        return genres
    except spotipy.SpotifyException:
        logger.exception("spotify_genres.error", track_id=track_id)
        return []
