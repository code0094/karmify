"""Application context: wires the backend together for the sidecar.

This is the sidecar's equivalent of ``main.py`` — it builds the DB engine,
Spotify clients, downloader, music sources and library manager, and exposes
high-level operations (fetch likes, search, download) that the HTTP routes call.
"""

from __future__ import annotations

import asyncio
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
        # Downloads in flight — a second click must not start a parallel fetch
        # of the same track (by liked-track id) or search result (by ref).
        self._downloading: set[int] = set()
        self._downloading_refs: set[str] = set()

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
        # Claim the slot before the first await: with a check-then-add split by
        # awaits, two concurrent clicks both pass the check and download twice.
        # Held until the DB write so the whole operation is single-flight.
        if track_id in self._downloading:
            raise SourceError(f"Track {track_id} is already being downloaded")
        self._downloading.add(track_id)
        try:
            async with self.session_factory() as session:
                track = await repos.get_track_by_id(session, track_id)
            if track is None:
                raise SourceError(f"Track {track_id} not found")
            if track.downloaded_at:
                raise SourceError(f"Track {track_id} is already downloaded")

            src = self._require_source(source)
            result = await self._resolve_candidate(src, source, track)

            # Claim the ref too: /sources/download works by ref, and without
            # this the same file could be fetched in parallel via both routes.
            if result.download_ref in self._downloading_refs:
                raise SourceError(f"Already downloading {result.download_ref}")
            self._downloading_refs.add(result.download_ref)
            try:
                path = await src.download(result, Path(self.settings.download_dir))
            finally:
                self._downloading_refs.discard(result.download_ref)

            # copy2 of a large FLAC would stall the event loop.
            await asyncio.to_thread(self.library.add, path, subdir=track.detected_genre)

            async with self.session_factory() as session:
                await repos.mark_track_downloaded(session, track_id, str(path))
        finally:
            self._downloading.discard(track_id)
        return path

    async def _resolve_candidate(
        self, src: MusicSource, source: str, track: LikedTrack
    ) -> SearchResult:
        """Find what to hand the source's download() for a liked track.

        Only Spotify can fetch by track id. Every other source needs a real
        search hit — its download() reads source-specific fields (a Soulseek
        username and file path, a Bandcamp URL) that a hand-built result from
        a Spotify id simply does not carry.
        """
        if source == "spotify":
            return SearchResult(
                source=source,
                title=track.track_name or "",
                artist=track.artist_name or "",
                download_ref=track.spotify_track_id,
            )

        query = f"{track.artist_name or ''} {track.track_name or ''}".strip()
        if not query:
            raise SourceError(f"Track {track.id} has no artist/title to search {source} with")

        candidates = await src.search(query, limit=10)
        if not candidates:
            raise SourceError(f"No {source} match for {query!r}")
        # Sources rank their own results (Soulseek puts lossless first).
        return candidates[0]

    async def search_sources(
        self, query: str, *, source: str, limit: int = 20
    ) -> list[SearchResult]:
        """Search a single source for candidate tracks."""
        return await self._require_source(source).search(query, limit=limit)

    async def download_result(self, result: SearchResult) -> Path:
        """Download an arbitrary search result and copy it into the library."""
        if result.download_ref in self._downloading_refs:
            raise SourceError(f"Already downloading {result.download_ref}")
        self._downloading_refs.add(result.download_ref)
        try:
            src = self._require_source(result.source)
            path = await src.download(result, Path(self.settings.download_dir))
            await asyncio.to_thread(self.library.add, path)
        finally:
            self._downloading_refs.discard(result.download_ref)
        return path

    def _require_source(self, source: str) -> MusicSource:
        if source not in self.sources:
            raise SourceError(f"Source not available/configured: {source}")
        return self.sources[source]

    async def aclose(self) -> None:
        """Release resources (DB engine) on shutdown."""
        await self.engine.dispose()
