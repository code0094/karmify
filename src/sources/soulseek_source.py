"""Soulseek music source via the slskd daemon (FLAC search/download).

We talk to a running slskd daemon over its REST API (through the synchronous
``slskd-api`` package, wrapped in threads). slskd handles the Soulseek protocol,
queues and shares; we just search, filter for lossless, enqueue, and collect the
finished file from slskd's downloads directory.

API method names follow slskd-api (https://slskd-api.readthedocs.io/); verify
against the installed version if slskd changes its REST surface.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

import structlog

from src.sources.base import MusicSource, SearchResult, SourceError

logger = structlog.get_logger()

_AUDIO_EXTS = {".flac", ".mp3", ".wav", ".aiff", ".aif", ".ogg", ".m4a", ".alac"}


def _ext_to_format(filename: str) -> str | None:
    suffix = Path(filename).suffix.lower().lstrip(".")
    return suffix or None


class SoulseekSource(MusicSource):
    """Searches and downloads from Soulseek through a slskd daemon."""

    name = "soulseek"

    def __init__(
        self,
        slskd_url: str,
        api_key: str,
        downloads_dir: str,
        *,
        search_timeout: float = 20.0,
        download_timeout: float = 600.0,
    ) -> None:
        if not slskd_url or not api_key:
            raise SourceError("slskd_url and slskd_api_key must be configured")
        self._url = slskd_url
        self._api_key = api_key
        self._downloads_dir = Path(downloads_dir) if downloads_dir else None
        self._search_timeout = search_timeout
        self._download_timeout = download_timeout

    def _client(self) -> Any:
        # Imported lazily so the rest of the app works without slskd-api installed.
        import slskd_api

        return slskd_api.SlskdClient(host=self._url, api_key=self._api_key)

    async def search(self, query: str, *, limit: int = 20) -> list[SearchResult]:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._search_blocking, query, limit),
                timeout=self._search_timeout + 10,
            )
        except TimeoutError as exc:
            raise SourceError(f"Soulseek search timed out for {query!r}") from exc

    def _search_blocking(self, query: str, limit: int) -> list[SearchResult]:
        import time

        client = self._client()
        search = client.searches.search_text(searchText=query)
        search_id = search["id"]

        # Wait for the search to complete (or until our soft timeout).
        deadline = time.monotonic() + self._search_timeout
        while time.monotonic() < deadline:
            state = client.searches.state(search_id)
            if state.get("isComplete") or state.get("state", "").lower().endswith("completed"):
                break
            time.sleep(1.0)

        responses = client.searches.search_responses(search_id)
        results: list[SearchResult] = []
        for resp in responses:
            username = resp.get("username", "")
            for f in resp.get("files", []):
                filename = f.get("filename", "")
                fmt = _ext_to_format(filename)
                if f".{fmt}" not in _AUDIO_EXTS:
                    continue
                results.append(
                    SearchResult(
                        source=self.name,
                        title=Path(filename).stem,
                        artist=username,
                        download_ref=f"{username}|{filename}",
                        audio_format=fmt,
                        bitrate=f.get("bitRate"),
                        size_bytes=f.get("size"),
                        duration_sec=f.get("length"),
                        extra={"username": username, "filename": filename},
                    )
                )

        # Lossless first, then by size (proxy for quality).
        results.sort(key=lambda r: (not r.is_lossless, -(r.size_bytes or 0)))
        return results[:limit]

    async def download(self, result: SearchResult, dest_dir: Path) -> Path:
        if self._downloads_dir is None:
            raise SourceError("slskd_downloads_dir must be configured to collect files")
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._download_blocking, result, dest_dir),
                timeout=self._download_timeout + 30,
            )
        except TimeoutError as exc:
            raise SourceError("Soulseek download timed out") from exc

    def _download_blocking(self, result: SearchResult, dest_dir: Path) -> Path:
        import time

        username = result.extra.get("username", "")
        filename = result.extra.get("filename", "")
        if not username or not filename:
            raise SourceError(
                "Soulseek downloads need a search result (username + filename in extra); "
                f"got download_ref={result.download_ref!r}"
            )

        client = self._client()
        size = result.size_bytes or 0

        client.transfers.enqueue(username=username, files=[{"filename": filename, "size": size}])

        basename = Path(filename.replace("\\", "/")).name
        deadline = time.monotonic() + self._download_timeout
        while time.monotonic() < deadline:
            found = self._find_completed(basename)
            if found is not None:
                dest_dir.mkdir(parents=True, exist_ok=True)
                final = dest_dir / basename
                if final.exists():
                    final.unlink()
                shutil.move(str(found), str(final))
                logger.info("source.soulseek.downloaded", file=basename, path=str(final))
                return final
            time.sleep(2.0)

        raise SourceError(f"Soulseek download did not complete: {basename}")

    def _find_completed(self, basename: str) -> Path | None:
        """Look for the finished file in slskd's downloads directory."""
        assert self._downloads_dir is not None
        if not self._downloads_dir.exists():
            return None
        for path in self._downloads_dir.rglob(basename):
            if path.is_file():
                return path
        return None
