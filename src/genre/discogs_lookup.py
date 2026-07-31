"""Search Discogs for genre and style information."""

import asyncio

import discogs_client
import structlog

logger = structlog.get_logger()


async def search_release(
    discogs: discogs_client.Client, artist_name: str, track_name: str
) -> tuple[list[str], str | None]:
    """Search Discogs once and return (genre+style tags, record label).

    One search serves both the genre cascade and the label lookup: Discogs is
    rate-limited to 60 requests/min, and the two used to issue identical queries.

    Returns:
        A ``(tags, label)`` pair; empty list and ``None`` when nothing is found
        or the API call fails.
    """
    try:
        query = f"{artist_name} {track_name}"
        results = await asyncio.to_thread(discogs.search, query, type="release")

        if not results or results.count == 0:
            return [], None

        release = results[0]
        tags: list[str] = list(release.genres or []) + list(release.styles or [])
        labels = release.labels
        label = str(labels[0].name) if labels else None

        logger.debug("discogs.result", artist=artist_name, track=track_name, tags=tags)
        return tags, label
    except Exception:
        logger.exception("discogs.error", artist=artist_name, track=track_name)
        return [], None


async def search_genre(
    discogs: discogs_client.Client, artist_name: str, track_name: str
) -> list[str]:
    """Search Discogs for a release and return genre + style tags."""
    tags, _ = await search_release(discogs, artist_name, track_name)
    return tags


async def get_label(
    discogs: discogs_client.Client, artist_name: str, track_name: str
) -> str | None:
    """Try to find the record label from Discogs."""
    _, label = await search_release(discogs, artist_name, track_name)
    return label
