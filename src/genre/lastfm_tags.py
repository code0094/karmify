"""Fetch top tags from Last.fm."""

import asyncio

import pylast
import structlog

logger = structlog.get_logger()


def _fetch_tags(network: pylast.LastFMNetwork, artist_name: str, track_name: str) -> list[str]:
    """Synchronous helper to fetch tags from Last.fm."""
    track = network.get_track(artist_name, track_name)
    top_tags = track.get_top_tags(limit=10)
    return [str(tag.item.get_name()) for tag in top_tags if int(tag.weight) > 30]


async def get_top_tags(
    network: pylast.LastFMNetwork, artist_name: str, track_name: str
) -> list[str]:
    """Get top tags for a track from Last.fm."""
    try:
        tags = await asyncio.to_thread(_fetch_tags, network, artist_name, track_name)
        logger.debug("lastfm.result", artist=artist_name, track=track_name, tags=tags)
        return tags
    except pylast.WSError:
        logger.debug("lastfm.not_found", artist=artist_name, track=track_name)
        return []
    except Exception:
        logger.exception("lastfm.error", artist=artist_name, track=track_name)
        return []
