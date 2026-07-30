"""Tests for the pluggable music sources."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.sources.base import SearchResult, SourceError
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


# ---- Soulseek download flow ----------------------------------------------


def _soulseek_result(size: int = 8) -> SearchResult:
    return SearchResult(
        source="soulseek",
        title="song",
        artist="u",
        download_ref=r"u|a\song.flac",
        size_bytes=size,
        extra={"username": "u", "filename": r"a\song.flac"},
    )


@pytest.mark.asyncio
async def test_soulseek_download_moves_file_from_nested_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloads = tmp_path / "slskd"
    nested = downloads / "u" / "music"
    nested.mkdir(parents=True)
    (nested / "song.flac").write_bytes(b"flacdata")

    src = SoulseekSource("http://x", "key", str(downloads))
    fake = MagicMock()
    monkeypatch.setattr(src, "_client", lambda: fake)

    dest = tmp_path / "out"
    path = await src.download(_soulseek_result(), dest)

    assert path == dest / "song.flac"
    assert path.read_bytes() == b"flacdata"
    assert not (nested / "song.flac").exists()  # moved, not copied
    fake.transfers.enqueue.assert_called_once_with(
        username="u", files=[{"filename": r"a\song.flac", "size": 8}]
    )


@pytest.mark.asyncio
async def test_soulseek_download_overwrites_existing_dest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloads = tmp_path / "slskd"
    downloads.mkdir()
    (downloads / "song.flac").write_bytes(b"fresh")
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "song.flac").write_bytes(b"stale")

    src = SoulseekSource("http://x", "key", str(downloads))
    monkeypatch.setattr(src, "_client", lambda: MagicMock())

    path = await src.download(_soulseek_result(), dest)

    assert path.read_bytes() == b"fresh"


@pytest.mark.asyncio
async def test_soulseek_download_polls_until_file_appears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wait loop really polls: the file appears only after the first sleep."""
    downloads = tmp_path / "slskd"
    downloads.mkdir()
    src = SoulseekSource("http://x", "key", str(downloads), download_timeout=30)
    monkeypatch.setattr(src, "_client", lambda: MagicMock())

    def sleep_plants_file(_seconds: float) -> None:
        (downloads / "song.flac").write_bytes(b"late")

    monkeypatch.setattr("time.sleep", sleep_plants_file)

    path = await src.download(_soulseek_result(), tmp_path / "out")

    assert path.read_bytes() == b"late"


@pytest.mark.asyncio
async def test_soulseek_download_timeout_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloads = tmp_path / "slskd"
    downloads.mkdir()
    src = SoulseekSource("http://x", "key", str(downloads), download_timeout=0)
    monkeypatch.setattr(src, "_client", lambda: MagicMock())

    with pytest.raises(SourceError, match="song.flac"):
        await src.download(_soulseek_result(), tmp_path / "out")


@pytest.mark.asyncio
async def test_soulseek_download_requires_downloads_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = SoulseekSource("http://x", "key", "")
    client_factory = MagicMock()
    monkeypatch.setattr(src, "_client", client_factory)

    with pytest.raises(SourceError, match="downloads_dir"):
        await src.download(_soulseek_result(), tmp_path / "out")
    client_factory.assert_not_called()  # fails before touching slskd


@pytest.mark.asyncio
async def test_soulseek_download_without_search_metadata_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hand-built result (no extra) used to reach slskd with empty fields."""
    src = SoulseekSource("http://x", "key", str(tmp_path))
    client_factory = MagicMock()
    monkeypatch.setattr(src, "_client", client_factory)
    bare = SearchResult(source="soulseek", title="t", artist="a", download_ref="spotify_id")

    with pytest.raises(SourceError, match="search result"):
        await src.download(bare, tmp_path / "out")
    client_factory.assert_not_called()
