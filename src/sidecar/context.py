"""Application context: wires the backend together for the sidecar.

This is the sidecar's equivalent of ``main.py`` — it builds the DB engine,
Spotify clients, downloader, music sources and library manager, and exposes
high-level operations (fetch likes, search, download) that the HTTP routes call.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import discogs_client
import pylast
import structlog

from src.db import repos
from src.db.engine import build_engine
from src.db.models import LikedTrack
from src.genre.pipeline import resolve_and_store_genre
from src.library.manager import LibraryManager
from src.sources.base import (
    AlreadyDownloadedError,
    DownloadInFlightError,
    MusicSource,
    SearchResult,
    SourceError,
)
from src.sources.spotify_source import SpotifySource
from src.spotify.client import SpotifyClient
from src.spotify.downloader import TrackDownloader
from src.spotify.oauth import SpotifyAuthFlow
from src.spotify.poller import poll_all_users

if TYPE_CHECKING:
    from src.config import Settings

logger = structlog.get_logger()

#: Batch downloads try sources in this order: lossless-capable first, the
#: Spotify 320 kbps ceiling as the last resort. Unconfigured sources are skipped.
SOURCE_PREFERENCE: tuple[str, ...] = ("soulseek", "bandcamp", "spotify")


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

        self.auth_flow = SpotifyAuthFlow(settings)
        self.downloader = TrackDownloader(settings)
        self.library = LibraryManager(settings.library_dir)
        self.sources = self._build_sources()
        # Ad-hoc search-result downloads in flight, keyed by ref. Liked tracks
        # use a database claim instead (see repos.claim_download) because the
        # bot process must see it too.
        self._downloading_refs: set[str] = set()
        # Background batch downloads, one task per playlist db id. In-process
        # is enough: all desktop clients talk to the same sidecar, and the
        # per-track DB claim still guards any overlap with the bot.
        self._playlist_tasks: dict[int, asyncio.Task[None]] = {}

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

    async def store_tokens(self, user_label: str, token_info: dict[str, Any]) -> None:
        """Persist tokens obtained through the browser authorization flow."""
        expires_at = datetime.now(tz=UTC) + timedelta(seconds=int(token_info["expires_in"]))
        async with self.session_factory() as session:
            await repos.save_tokens(
                session,
                user_label=user_label,
                access_token=token_info["access_token"],
                refresh_token=token_info["refresh_token"],
                expires_at=expires_at,
            )
        logger.info("spotify_auth.tokens_stored", user=user_label)

    async def fetch_likes(self) -> int:
        """Poll Spotify for new likes for all users; returns count of new tracks."""
        return await poll_all_users(self.all_clients, self.session_factory, self._on_new_track)

    async def download_liked_track(self, track_id: int, *, source: str = "spotify") -> Path:
        """Download a liked track's audio, copy to library, mark it downloaded."""
        async with self.session_factory() as session:
            track = await repos.get_track_by_id(session, track_id)
        if track is None:
            raise SourceError(f"Track {track_id} not found")
        if track.downloaded_at:
            raise AlreadyDownloadedError(f"Track {track_id} is already downloaded")

        # The claim lives in the database: the bot is a separate process, so an
        # in-memory guard would not see a download it started for this track.
        async with self.session_factory() as session:
            claimed = await repos.claim_download(
                session, track_id, stale_after_sec=self.settings.download_timeout_sec * 2
            )
        if not claimed:
            raise DownloadInFlightError(f"Track {track_id} is already being downloaded")

        try:
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
        except BaseException:
            # Release the claim so a retry is possible (mark_track_downloaded
            # clears it on the success path).
            async with self.session_factory() as session:
                await repos.release_download(session, track_id)
            raise
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

    def playlist_download_running(self, playlist_db_id: int) -> bool:
        """Whether a batch download for this playlist is still in flight."""
        task = self._playlist_tasks.get(playlist_db_id)
        return task is not None and not task.done()

    async def start_playlist_download(self, playlist_db_id: int, spotify_playlist_id: str) -> int:
        """Queue background downloads for every undownloaded track; returns the count.

        Returns immediately — the work continues in a background task, and the
        client follows progress by re-reading /playlists (fire-and-poll).
        """
        if self.playlist_download_running(playlist_db_id):
            raise DownloadInFlightError(f"Playlist {playlist_db_id} download is already running")
        async with self.session_factory() as session:
            tracks = await repos.list_playlist_tracks(
                session, spotify_playlist_id, only_undownloaded=True
            )
        if not tracks:
            return 0
        track_ids = [t.id for t in tracks]
        self._playlist_tasks[playlist_db_id] = asyncio.create_task(
            self._playlist_worker(playlist_db_id, track_ids)
        )
        return len(track_ids)

    async def _playlist_worker(self, playlist_db_id: int, track_ids: list[int]) -> None:
        """Download a playlist's tracks one by one; failures are per-track."""
        logger.info("playlist_download.started", playlist=playlist_db_id, tracks=len(track_ids))
        for track_id in track_ids:
            try:
                await self.download_track_any_source(track_id)
            except asyncio.CancelledError:
                logger.info("playlist_download.cancelled", playlist=playlist_db_id)
                raise
            except Exception:
                # One broken track must not stop the rest of the batch.
                logger.exception("playlist_download.track_failed", track=track_id)
        logger.info("playlist_download.finished", playlist=playlist_db_id)

    async def download_track_any_source(self, track_id: int) -> None:
        """Try every configured source in preference order; record the failure.

        Never raises for a plain source failure — the batch runs unattended,
        so the error's place is the track row (shown as ❌ in the UI), not an
        exception nobody catches.
        """
        order = [name for name in SOURCE_PREFERENCE if name in self.sources]
        last_error = "no download sources are configured"
        for source in order:
            try:
                await self.download_liked_track(track_id, source=source)
                return
            except (AlreadyDownloadedError, DownloadInFlightError):
                return  # someone else already has it — not a failure
            except SourceError as exc:
                last_error = str(exc)
                logger.warning(
                    "download.source_failed", track=track_id, source=source, error=last_error
                )
        async with self.session_factory() as session:
            await repos.set_download_error(session, track_id, last_error)

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
        """Cancel running batch downloads and release the DB engine.

        Cancellation lands inside download_liked_track, whose BaseException
        handler releases the per-track claim — an interrupted batch leaves no
        track stuck in "downloading".
        """
        running = [t for t in self._playlist_tasks.values() if not t.done()]
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        await self.engine.dispose()
