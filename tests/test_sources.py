"""Tests for the pluggable music sources."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.sources.base import SearchResult
from src.sources.soulseek_source import SoulseekSource
from src.sources.spotify_source import SpotifySource


def test_search_result_is_lossless() -> None:
    flac = SearchResult(source="s", title="t", artist="a", download_ref="r", audio_format="flac")
    mp3 = SearchResult(source="s", title="t", artist="a", download_ref="r", audio_format="mp3")
    none = SearchResult(source="s", title="t", artist="a", download_ref="r")
    assert flac.is_lossless
    assert not mp3.is_lossless
    assert not none.is_lossless


@pytest.mark.asyncio
async def test_spotify_search_maps_results() -> None:
    sp = MagicMock()
    sp.search.return_value = {
        "tracks": {
            "items": [
                {
                    "name": "Akephale",
                    "artists": [{"name": "ROD"}, {"name": "X"}],
                    "id": "t1",
                    "duration_ms": 372000,
                    "album": {"name": "Album"},
                }
            ]
        }
    }

    async def get_sp() -> MagicMock:
        return sp

    src = SpotifySource(MagicMock(), get_sp)
    results = await src.search("rod")

    assert len(results) == 1
    assert results[0].download_ref == "t1"
    assert results[0].artist == "ROD, X"
    assert results[0].duration_sec == 372


@pytest.mark.asyncio
async def test_spotify_download_moves_into_dest(tmp_path: Path) -> None:
    downloaded = tmp_path / "cache" / "track.mp3"
    downloaded.parent.mkdir()
    downloaded.write_bytes(b"audio")

    downloader = MagicMock()
    downloader.download = AsyncMock(return_value=downloaded)

    async def get_sp() -> MagicMock:
        return MagicMock()

    src = SpotifySource(downloader, get_sp)
    dest = tmp_path / "out"
    result = SearchResult(source="spotify", title="t", artist="a", download_ref="t1")

    path = await src.download(result, dest)

    assert path.exists()
    assert path.parent == dest
    assert path.read_bytes() == b"audio"


@pytest.mark.asyncio
async def test_soulseek_search_filters_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    src = SoulseekSource("http://x", "key", "/dl", search_timeout=0)

    fake = MagicMock()
    fake.searches.search_text.return_value = {"id": "s1"}
    fake.searches.state.return_value = {"isComplete": True}
    fake.searches.search_responses.return_value = [
        {
            "username": "u",
            "files": [
                {"filename": "a\\song.mp3", "size": 500, "bitRate": 320, "length": 300},
                {"filename": "a\\song.flac", "size": 30000, "bitRate": 900, "length": 300},
                {"filename": "a\\readme.txt", "size": 10},
            ],
        }
    ]
    monkeypatch.setattr(src, "_client", lambda: fake)

    results = await src.search("song")

    # .txt filtered out; lossless (flac) sorted before mp3
    assert [r.audio_format for r in results] == ["flac", "mp3"]
    assert results[0].extra["username"] == "u"
