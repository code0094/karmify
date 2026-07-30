"""Tests for AppContext: source registry and high-level operations.

AppContext is constructed for real (no network I/O in the constructor: the DB
engine is created but never connects, OAuth/discogs/pylast are plain config
objects); only the DB repo calls and the sources themselves are substituted.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

import src.sidecar.context as ctxmod
from src.config import Settings
from src.db.models import LikedTrack
from src.sidecar.context import AppContext
from src.sources.base import MusicSource, SearchResult, SourceError


class FakeSource(MusicSource):
    """In-memory source: records download calls, returns a fixed path."""

    name = "fake"

    def __init__(self) -> None:
        self.downloads: list[SearchResult] = []
        self.searched: list[str] = []
        self.results = [
            SearchResult(source="spotify", title="Akephale", artist="ROD", download_ref="t1")
        ]

    async def search(self, query: str, *, limit: int = 20) -> list[SearchResult]:
        self.searched.append(query)
        return self.results

    async def download(self, result: SearchResult, dest_dir: Path) -> Path:
        self.downloads.append(result)
        return dest_dir / "ROD - Akephale.mp3"


def test_sources_default_is_spotify_only(make_settings: Callable[..., Settings]) -> None:
    ctx = AppContext(make_settings())
    assert set(ctx.sources) == {"spotify"}


def test_soulseek_enabled_by_config(make_settings: Callable[..., Settings]) -> None:
    ctx = AppContext(
        make_settings(slskd_url="http://x", slskd_api_key="k", slskd_downloads_dir="dl")
    )
    assert set(ctx.sources) == {"spotify", "soulseek"}


def test_partial_soulseek_config_is_ignored(make_settings: Callable[..., Settings]) -> None:
    """URL without an API key must not enable the source (and must not crash)."""
    ctx = AppContext(make_settings(slskd_url="http://x"))
    assert set(ctx.sources) == {"spotify"}


def test_bandcamp_enabled_by_config(make_settings: Callable[..., Settings]) -> None:
    ctx = AppContext(
        make_settings(bandcamp_mail_address="dj@example.com", bandcamp_mail_password="pw")
    )
    assert set(ctx.sources) == {"spotify", "bandcamp"}


@pytest.mark.asyncio
async def test_unknown_source_raises(make_settings: Callable[..., Settings]) -> None:
    ctx = AppContext(make_settings())
    with pytest.raises(SourceError, match="nope"):
        await ctx.search_sources("query", source="nope")


@pytest.mark.asyncio
async def test_search_sources_delegates(make_settings: Callable[..., Settings]) -> None:
    ctx = AppContext(make_settings())
    ctx.sources["spotify"] = FakeSource()

    results = await ctx.search_sources("rod akephale", source="spotify")

    assert len(results) == 1
    assert results[0].download_ref == "t1"


@pytest.mark.asyncio
async def test_download_liked_track_lands_in_genre_subdir(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = AppContext(make_settings(download_dir=str(tmp_path)))
    fake = FakeSource()
    ctx.sources["spotify"] = fake
    ctx.library = MagicMock()

    track = LikedTrack(
        id=7,
        spotify_track_id="t1",
        track_name="Akephale",
        artist_name="ROD",
        liked_by="karma",
        detected_genre="hardgroove",
    )
    monkeypatch.setattr(ctxmod.repos, "get_track_by_id", AsyncMock(return_value=track))
    mark = AsyncMock()
    monkeypatch.setattr(ctxmod.repos, "mark_track_downloaded", mark)

    path = await ctx.download_liked_track(7, source="spotify")

    assert fake.downloads[0].download_ref == "t1"
    ctx.library.add.assert_called_once_with(path, subdir="hardgroove")
    mark.assert_awaited_once_with(ANY, 7, str(path))


@pytest.mark.asyncio
async def test_download_liked_track_missing_track(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AppContext(make_settings())
    monkeypatch.setattr(ctxmod.repos, "get_track_by_id", AsyncMock(return_value=None))

    with pytest.raises(SourceError, match="not found"):
        await ctx.download_liked_track(99)


@pytest.mark.asyncio
async def test_download_result_no_subdir(
    make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    ctx = AppContext(make_settings(download_dir=str(tmp_path)))
    ctx.sources["spotify"] = FakeSource()
    ctx.library = MagicMock()

    result = SearchResult(source="spotify", title="T", artist="A", download_ref="t1")
    path = await ctx.download_result(result)

    ctx.library.add.assert_called_once_with(path)


@pytest.mark.asyncio
async def test_download_liked_track_searches_non_spotify_sources(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Soulseek/Bandcamp downloads need a real search hit: their download()
    reads source-specific fields a Spotify id cannot provide."""
    ctx = AppContext(make_settings(download_dir=str(tmp_path)))
    fake = FakeSource()
    ctx.sources["soulseek"] = fake
    ctx.library = MagicMock()

    track = LikedTrack(
        id=7, spotify_track_id="t1", track_name="Akephale", artist_name="ROD", liked_by="karma"
    )
    monkeypatch.setattr(ctxmod.repos, "get_track_by_id", AsyncMock(return_value=track))
    monkeypatch.setattr(ctxmod.repos, "mark_track_downloaded", AsyncMock())

    await ctx.download_liked_track(7, source="soulseek")

    # The search hit was downloaded, not a hand-built result from the track id.
    assert fake.downloads[0].download_ref == "t1"
    assert fake.searched == ["ROD Akephale"]


@pytest.mark.asyncio
async def test_download_liked_track_no_match(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AppContext(make_settings())
    empty = FakeSource()
    empty.results = []
    ctx.sources["soulseek"] = empty
    monkeypatch.setattr(
        ctxmod.repos,
        "get_track_by_id",
        AsyncMock(return_value=LikedTrack(id=7, spotify_track_id="t1", artist_name="ROD")),
    )

    with pytest.raises(SourceError, match="No soulseek match"):
        await ctx.download_liked_track(7, source="soulseek")


@pytest.mark.asyncio
async def test_download_liked_track_rejects_already_downloaded(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AppContext(make_settings())
    done = LikedTrack(
        id=7, spotify_track_id="t1", liked_by="karma", downloaded_at=datetime(2026, 7, 1)
    )
    monkeypatch.setattr(ctxmod.repos, "get_track_by_id", AsyncMock(return_value=done))

    with pytest.raises(SourceError, match="already downloaded"):
        await ctx.download_liked_track(7)


@pytest.mark.asyncio
async def test_download_liked_track_is_single_flight(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The second concurrent call must be refused, and the slot must free up."""
    ctx = AppContext(make_settings(download_dir=str(tmp_path)))
    slow = FakeSource()
    gate = asyncio.Event()

    async def slow_download(result: SearchResult, dest_dir: Path) -> Path:
        await gate.wait()
        return dest_dir / "done.mp3"

    slow.download = slow_download  # type: ignore[method-assign]
    ctx.sources["spotify"] = slow
    ctx.library = MagicMock()

    track = LikedTrack(id=7, spotify_track_id="t1", track_name="A", liked_by="karma")
    monkeypatch.setattr(ctxmod.repos, "get_track_by_id", AsyncMock(return_value=track))
    monkeypatch.setattr(ctxmod.repos, "mark_track_downloaded", AsyncMock())

    first = asyncio.create_task(ctx.download_liked_track(7))
    await asyncio.sleep(0.01)  # let it claim the slot and block on the gate

    with pytest.raises(SourceError, match="already being downloaded"):
        await ctx.download_liked_track(7)

    gate.set()
    await first
    # Slot released: a new call gets past the guard (fails later on re-check).
    with pytest.raises(SourceError, match="not found"):
        monkeypatch.setattr(ctxmod.repos, "get_track_by_id", AsyncMock(return_value=None))
        await ctx.download_liked_track(7)
