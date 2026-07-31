"""Download track audio via zotify (subprocess CLI).

zotify pulls audio directly from Spotify (librespot), so it authenticates with a
logged-in account stored in a credentials file. Use a *burner* Premium account —
never the DJs' working accounts: this violates Spotify ToS and risks a ban, which
would also take down the liked-tracks monitoring that runs on the same accounts.

We invoke zotify as a subprocess (not as a library) for isolation: a hung or
crashed download cannot take the bot's event loop down with it, and we get hard
timeouts plus a concurrency limit for free.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from src.sources.base import SourceError

if TYPE_CHECKING:
    from src.config import Settings

logger = structlog.get_logger()

_AUDIO_EXTENSIONS = {".mp3", ".ogg", ".opus", ".m4a", ".aac", ".flac", ".wav"}
_TRACK_ID_RE = re.compile(r"[A-Za-z0-9]{22}")  # Spotify base62 track id


class DownloadError(SourceError):
    """Raised when a track download fails.

    Subclasses :class:`SourceError` so transport layers that map source
    failures (the sidecar's 502 handler) treat zotify failures the same way
    as Soulseek/Bandcamp ones instead of bubbling a bare 500.
    """


class TrackDownloader:
    """Downloads track audio on demand via the zotify CLI."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.download_concurrency)
        self._dest = Path(settings.download_dir)

    @staticmethod
    def _track_url(spotify_track_id: str) -> str:
        return f"https://open.spotify.com/track/{spotify_track_id}"

    async def download(self, spotify_track_id: str) -> Path:
        """Download one track and return the path to the resulting audio file.

        Args:
            spotify_track_id: The Spotify track ID (not a full URL).

        Returns:
            Path to the downloaded audio file inside ``download_dir``.

        Raises:
            DownloadError: If zotify is missing, times out, exits non-zero, or
                produces no audio file.
        """
        async with self._semaphore:
            return await self._run(spotify_track_id)

    async def _run(self, spotify_track_id: str) -> Path:
        # The id becomes a directory name that is later rmtree'd — a value with
        # separators or ".." would take that deletion outside download_dir.
        if not _TRACK_ID_RE.fullmatch(spotify_track_id):
            raise DownloadError(f"недопустимый id трека: {spotify_track_id!r}")

        s = self._settings
        self._dest.mkdir(parents=True, exist_ok=True)

        # Download into a per-track scratch dir so we can reliably identify the
        # resulting file regardless of zotify's naming template.
        work = self._dest / ".part" / spotify_track_id
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)

        args = [
            "zotify",
            self._track_url(spotify_track_id),
            "--root-path",
            str(work),
            "--codec",
            s.download_format,
            "-q",
            s.download_quality,
        ]
        if s.zotify_credentials_path:
            args += ["--credentials-location", s.zotify_credentials_path]

        logger.info("download.start", track=spotify_track_id, fmt=s.download_format)

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            raise DownloadError("zotify не найден в PATH — установлен ли он?") from exc

        try:
            stdout_bytes, _ = await asyncio.wait_for(
                proc.communicate(), timeout=s.download_timeout_sec
            )
        except TimeoutError:
            await self._abandon(proc, work)
            raise DownloadError(f"таймаут {s.download_timeout_sec}s") from None
        except asyncio.CancelledError:
            # Shutdown mid-download: without this the zotify process outlives
            # us and its scratch directory is left behind.
            await self._abandon(proc, work)
            raise

        output = (stdout_bytes or b"").decode("utf-8", "replace")

        if proc.returncode != 0:
            logger.error(
                "download.failed",
                track=spotify_track_id,
                rc=proc.returncode,
                output=output[-500:],
            )
            shutil.rmtree(work, ignore_errors=True)
            raise DownloadError(f"zotify завершился с кодом {proc.returncode}")

        audio = self._find_audio(work)
        if audio is None:
            logger.error("download.no_file", track=spotify_track_id, output=output[-500:])
            shutil.rmtree(work, ignore_errors=True)
            raise DownloadError("аудиофайл не найден после загрузки")

        final = self._dest / audio.name
        if final.exists():
            final.unlink()
        shutil.move(str(audio), str(final))
        shutil.rmtree(work, ignore_errors=True)

        logger.info("download.done", track=spotify_track_id, path=str(final))
        return final

    @staticmethod
    async def _abandon(proc: asyncio.subprocess.Process, work: Path) -> None:
        """Kill a running zotify and drop its scratch directory."""
        proc.kill()
        await proc.wait()
        shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def _find_audio(directory: Path) -> Path | None:
        """Return the largest audio file under ``directory``, or None."""
        candidates = [
            p
            for p in directory.rglob("*")
            if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_size)
