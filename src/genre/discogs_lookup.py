"""Search Discogs for genre and style information."""

import asyncio

import discogs_client
import structlog

logger = structlog.get_logger()


async def search_genre(
    discogs: discogs_client.Client, artist_name: str, track_name: str
) -> list[str]:
    """Search Discogs for a release and return genre + style tags."""
    try:
        query = f"{artist_name} {track_name}"
        results = await asyncio.to_thread(discogs.search, query, type="release")

        if not results or results.count == 0:
            return []

        release = results[0]
        genres: list[str] = list(release.genres or [])
        styles: list[str] = list(release.styles or [])

        all_tags = genres + styles
        logger.debug(
            "discogs.result", artist=artist_name, track=track_name, tags=all_tags
        )
        return all_tags
    except Exception:
        logger.exception("discogs.error", artist=artist_name, track=track_name)
        return []


async def get_label(
    discogs: discogs_client.Client, artist_name: str, track_name: str
) -> str | None:
    """Try to find the record label from Discogs."""
    try:
        query = f"{artist_name} {track_name}"
        results = await asyncio.to_thread(discogs.search, query, type="release")
        if results and results.count > 0:
            release = results[0]
            labels = release.labels
            if labels:
                return str(labels[0].name)
    except Exception:
        logger.exception("discogs.label_error", artist=artist_name, track=track_name)
    return None
