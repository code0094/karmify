"""Spotify music source — search via the Web API, download via zotify."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from src.sources.base import MusicSource, SearchResult, SourceError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import spotipy

    from src.spotify.downloader import TrackDownloader

logger = structlog.get_logger()


class SpotifySource(MusicSource):
    """Searches Spotify's catalog and downloads audio through the zotify wrapper."""

    name = "spotify"

    def __init__(
        self,
        downloader: TrackDownloader,
        get_sp: Callable[[], Awaitable[spotipy.Spotify]],
    ) -> None:
        self._downloader = downloader
        self._get_sp = get_sp

    async def search(self, query: str, *, limit: int = 20) -> list[SearchResult]:
        sp = await self._get_sp()
        try:
            data = await asyncio.to_thread(sp.search, q=query, type="track", limit=min(limit, 50))
        except Exception as exc:  # spotipy raises various exceptions
            raise SourceError(f"Spotify search failed: {exc}") from exc

        results: list[SearchResult] = []
        for item in data.get("tracks", {}).get("items", []):
            results.append(
                SearchResult(
                    source=self.name,
                    title=item["name"],
                    artist=", ".join(a["name"] for a in item["artists"]),
                    download_ref=item["id"],
                    duration_sec=(item.get("duration_ms") or 0) // 1000,
                    extra={"album": item.get("album", {}).get("name")},
                )
            )
        return results

    async def download(self, result: SearchResult, dest_dir: Path) -> Path:
        # TrackDownloader writes into its own configured download_dir; move the
        # finished file into dest_dir so the caller controls placement.
        path = await self._downloader.download(result.download_ref)

        dest_dir.mkdir(parents=True, exist_ok=True)
        final = dest_dir / path.name
        if path.resolve() == final.resolve():
            return path
        if final.exists():
            final.unlink()
        await asyncio.to_thread(shutil.move, str(path), str(final))
        logger.info("source.spotify.downloaded", track=result.download_ref, path=str(final))
        return final
