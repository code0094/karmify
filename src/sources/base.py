"""Common interface and result model shared by all music sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """A single track candidate returned by a music source.

    ``download_ref`` is source-specific and is what :meth:`MusicSource.download`
    needs to fetch the file:
      - spotify  → Spotify track ID
      - soulseek → ``f"{username}\\{filepath}"`` from slskd
      - bandcamp → public track/album URL
    """

    source: str
    title: str
    artist: str
    download_ref: str
    audio_format: str | None = None  # 'flac' | 'mp3' | 'ogg' | ...
    bitrate: int | None = None  # kbps
    size_bytes: int | None = None
    duration_sec: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_lossless(self) -> bool:
        """Whether the candidate is a lossless format (FLAC/WAV/AIFF/ALAC)."""
        return (self.audio_format or "").lower() in {"flac", "wav", "aiff", "aif", "alac"}


class MusicSource(ABC):
    """Abstract music source: searchable and downloadable."""

    #: Stable identifier, e.g. "spotify" | "soulseek" | "bandcamp".
    name: str

    @abstractmethod
    async def search(self, query: str, *, limit: int = 20) -> list[SearchResult]:
        """Search the source and return candidate tracks (best-effort, may be empty)."""

    @abstractmethod
    async def download(self, result: SearchResult, dest_dir: Path) -> Path:
        """Download ``result`` into ``dest_dir`` and return the resulting file path."""


class SourceError(Exception):
    """Raised when a source operation (search or download) fails."""
