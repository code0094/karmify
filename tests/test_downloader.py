"""Tests for TrackDownloader: the zotify subprocess flow (no real zotify)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest

import src.spotify.downloader as dlmod
from src.config import Settings
from src.spotify.downloader import DownloadError, TrackDownloader

TRACK_ID = "3n3Ppam7vgaVa1iaRUc9Lp"  # 22-char Spotify base62 id


class FakeProc:
    """Stand-in for an asyncio subprocess."""

    def __init__(self, returncode: int = 0, output: bytes = b"", delay: float = 0.0) -> None:
        self.returncode = returncode
        self._output = output
        self._delay = delay
        self.killed = False

    async def communicate(self) -> tuple[bytes, None]:
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._output, None

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


def install_fake_exec(
    monkeypatch: pytest.MonkeyPatch,
    proc: FakeProc,
    *,
    drop_file: str | None = "ROD - Akephale.mp3",
    captured: list[str] | None = None,
) -> None:
    """Replace create_subprocess_exec: optionally drop an audio file into --root-path."""

    async def fake_exec(*args: str, **_kwargs: object) -> FakeProc:
        if captured is not None:
            captured.extend(args)
        root = Path(args[args.index("--root-path") + 1])
        if drop_file:
            (root / drop_file).write_bytes(b"a" * 64)
        return proc

    monkeypatch.setattr(dlmod.asyncio, "create_subprocess_exec", fake_exec)


@pytest.mark.asyncio
async def test_download_success_moves_file_and_cleans_up(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: list[str] = []
    install_fake_exec(monkeypatch, FakeProc(), captured=captured)
    d = TrackDownloader(make_settings(download_dir=str(tmp_path)))

    path = await d.download(TRACK_ID)

    assert path == tmp_path / "ROD - Akephale.mp3"
    assert path.read_bytes() == b"a" * 64
    assert not (tmp_path / ".part" / TRACK_ID).exists()
    assert f"https://open.spotify.com/track/{TRACK_ID}" in captured
    assert "--credentials-location" not in captured  # not configured


@pytest.mark.asyncio
async def test_download_passes_credentials_when_configured(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: list[str] = []
    install_fake_exec(monkeypatch, FakeProc(), captured=captured)
    d = TrackDownloader(
        make_settings(download_dir=str(tmp_path), zotify_credentials_path="creds.json")
    )

    await d.download(TRACK_ID)

    assert "--credentials-location" in captured
    assert "creds.json" in captured


@pytest.mark.asyncio
async def test_download_overwrites_existing_file(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "ROD - Akephale.mp3").write_bytes(b"stale")
    install_fake_exec(monkeypatch, FakeProc())
    d = TrackDownloader(make_settings(download_dir=str(tmp_path)))

    path = await d.download(TRACK_ID)

    assert path.read_bytes() == b"a" * 64


@pytest.mark.asyncio
async def test_download_nonzero_exit(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_fake_exec(monkeypatch, FakeProc(returncode=2, output=b"boom"))
    d = TrackDownloader(make_settings(download_dir=str(tmp_path)))

    with pytest.raises(DownloadError, match="кодом 2"):
        await d.download(TRACK_ID)
    assert not (tmp_path / ".part" / TRACK_ID).exists()


@pytest.mark.asyncio
async def test_download_no_audio_produced(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_fake_exec(monkeypatch, FakeProc(), drop_file=None)
    d = TrackDownloader(make_settings(download_dir=str(tmp_path)))

    with pytest.raises(DownloadError, match="не найден"):
        await d.download(TRACK_ID)


@pytest.mark.asyncio
async def test_download_zotify_missing(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def raise_missing(*_args: str, **_kwargs: object) -> FakeProc:
        raise FileNotFoundError("zotify")

    monkeypatch.setattr(dlmod.asyncio, "create_subprocess_exec", raise_missing)
    d = TrackDownloader(make_settings(download_dir=str(tmp_path)))

    with pytest.raises(DownloadError, match="PATH"):
        await d.download(TRACK_ID)


@pytest.mark.asyncio
async def test_download_timeout_kills_process(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proc = FakeProc(delay=5.0)
    install_fake_exec(monkeypatch, proc)
    settings = make_settings(download_dir=str(tmp_path))
    settings.download_timeout_sec = 0.05  # bypass ge=10 floor for the test
    d = TrackDownloader(settings)

    with pytest.raises(DownloadError, match="таймаут"):
        await d.download(TRACK_ID)
    assert proc.killed


def test_find_audio_picks_largest(tmp_path: Path) -> None:
    (tmp_path / "small.mp3").write_bytes(b"x" * 10)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "big.flac").write_bytes(b"x" * 100)
    (tmp_path / "notes.txt").write_bytes(b"x" * 999)

    found = TrackDownloader._find_audio(tmp_path)

    assert found is not None
    assert found.name == "big.flac"


def test_find_audio_empty(tmp_path: Path) -> None:
    assert TrackDownloader._find_audio(tmp_path) is None


@pytest.mark.asyncio
async def test_download_rejects_unsafe_track_id(
    make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    """The id becomes a directory that is later rmtree'd."""
    d = TrackDownloader(make_settings(download_dir=str(tmp_path)))

    with pytest.raises(DownloadError, match="недопустимый id"):
        await d.download("../../etc")


@pytest.mark.asyncio
async def test_cancellation_kills_process_and_cleans_up(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Shutdown mid-download must not orphan zotify or leave .part behind."""
    proc = FakeProc(delay=30.0)
    install_fake_exec(monkeypatch, proc)
    d = TrackDownloader(make_settings(download_dir=str(tmp_path)))

    task = asyncio.create_task(d.download(TRACK_ID))
    await asyncio.sleep(0.05)  # let it spawn and start waiting
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert proc.killed
    assert not (tmp_path / ".part" / TRACK_ID).exists()
