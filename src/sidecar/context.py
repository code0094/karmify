"""Application context: wires the backend together for the sidecar.

This is the sidecar's equivalent of ``main.py`` — it builds the DB engine,
Spotify clients, downloader, music sources and library manager, and exposes
high-level operations (fetch likes, search, download) that the HTTP routes call.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import discogs_client
import pylast
import structlog

from src.db import repos
from src.db.engine import build_engine
from src.db.models import LikedTrack
from src.genre.pipeline import resolve_and_store_genre
from src.library.manager import LibraryManager
from src.sources.base import MusicSource, SearchResult, SourceError
from src.sources.spotify_source import SpotifySource
from src.spotify.client import SpotifyClient
from src.spotify.downloader import TrackDownloader
from src.spotify.poller import poll_all_users

if TYPE_CHECKING:
    from src.config import Settings

logger = structlog.get_logger()


class AppContext:
    """Holds all backend dependencies and high-level operations for the sidecar."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine, self.session_factory = build_engine(settings)

        self.spotify_clients: dict[str, SpotifyClient] = {
            "karma": SpotifyClient("karma", settings, self.session_factory),
            "stress303": SpotifyClient("stress303", settings, self.session_factory),
        }
        self.all_clients = list(self.spotify_clients.values())

        self.discogs = discogs_client.Client(
            "AuxDJBot/0.1", user_token=settings.discogs_user_token
        )
        self.lastfm = pylast.LastFMNetwork(
            api_key=settings.lastfm_api_key, api_secret=settings.lastfm_api_secret
        )

        self.downloader = TrackDownloader(settings)
        self.library = LibraryManager(settings.library_dir)
        self.sources = self._build_sources()

    def _build_sources(self) -> dict[str, MusicSource]:
        """Construct the available music sources based on configuration."""
        sources: dict[str, MusicSource] = {
            "spotify": SpotifySource(
                self.downloader,
                get_sp=lambda: self.spotify_clients["karma"].get_client(),
            )
        }

        if self.settings.slskd_url and self.settings.slskd_api_key:
            from src.sources.soulseek_source import SoulseekSource

            sources["soulseek"] = SoulseekSource(
                self.settings.slskd_url,
                self.settings.slskd_api_key,
                self.settings.slskd_downloads_dir,
            )

        if self.settings.bandcamp_mail_address:
            from src.sources.bandcamp_source import BandcampSource
            from src.sources.mailbox import Mailbox

            mailbox = Mailbox(
                self.settings.bandcamp_mail_imap_host,
                self.settings.bandcamp_mail_address,
                self.settings.bandcamp_mail_password,
            )
            sources["bandcamp"] = BandcampSource(
                mailbox,
                self.settings.bandcamp_mail_address,
                captcha_api_key=self.settings.captcha_api_key,
            )

        return sources

    async def _on_new_track(self, track: LikedTrack) -> None:
        """Resolve genre for a newly detected like and persist it (no Telegram)."""
        sp = await self.spotify_clients[track.liked_by].get_client()
        await resolve_and_store_genre(
            track,
            sp=sp,
            discogs=self.discogs,
            lastfm=self.lastfm,
            session_factory=self.session_factory,
        )

    async def fetch_likes(self) -> int:
        """Poll Spotify for new likes for all users; returns count of new tracks."""
        return await poll_all_users(self.all_clients, self.session_factory, self._on_new_track)

    async def download_liked_track(self, track_id: int, *, source: str = "spotify") -> Path:
        """Download a liked track's audio, copy to library, mark it downloaded."""
        async with self.session_factory() as session:
            track = await repos.get_track_by_id(session, track_id)
        if track is None:
            raise SourceError(f"Track {track_id} not found")

        src = self._require_source(source)
        result = SearchResult(
            source=source,
            title=track.track_name or "",
            artist=track.artist_name or "",
            download_ref=track.spotify_track_id,
        )
        path = await src.download(result, Path(self.settings.download_dir))
        self.library.add(path, subdir=track.detected_genre)

        async with self.session_factory() as session:
            await repos.mark_track_downloaded(session, track_id, str(path))
        return path

    async def search_sources(
        self, query: str, *, source: str, limit: int = 20
    ) -> list[SearchResult]:
        """Search a single source for candidate tracks."""
        return await self._require_source(source).search(query, limit=limit)

    async def download_result(self, result: SearchResult) -> Path:
        """Download an arbitrary search result and copy it into the library."""
        src = self._require_source(result.source)
        path = await src.download(result, Path(self.settings.download_dir))
        self.library.add(path)
        return path

    def _require_source(self, source: str) -> MusicSource:
        if source not in self.sources:
            raise SourceError(f"Source not available/configured: {source}")
        return self.sources[source]

    async def aclose(self) -> None:
        """Release resources (DB engine) on shutdown."""
        await self.engine.dispose()
