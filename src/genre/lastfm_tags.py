"""Fetch top tags from Last.fm."""

import asyncio

import pylast
import structlog

logger = structlog.get_logger()


def _weighted(tags: list) -> list[str]:  # type: ignore[type-arg]
    """Tag names above the noise floor; pylast reports weights as strings."""
    return [str(tag.item.get_name()) for tag in tags if int(tag.weight) > 30]


def _fetch_tags(network: pylast.LastFMNetwork, artist_name: str, track_name: str) -> list[str]:
    """Track tags, falling back to the artist's when the track has none.

    Niche club tracks routinely carry no tags at all while the artist is
    tagged precisely — Jeff Mills has 'techno'/'detroit techno' even where
    "The Bells" has nothing. Without the fallback those tracks always end up
    classified by hand.
    """
    track_tags = _weighted(network.get_track(artist_name, track_name).get_top_tags(limit=10))
    if track_tags:
        return track_tags
    return _weighted(network.get_artist(artist_name).get_top_tags(limit=10))


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
