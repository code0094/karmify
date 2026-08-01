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


def _stub_claim(monkeypatch: pytest.MonkeyPatch, *, claimed: bool = True) -> AsyncMock:
    """Stub the DB-backed download claim (exercised for real in test_repos.py)."""
    monkeypatch.setattr(ctxmod.repos, "claim_download", AsyncMock(return_value=claimed))
    release = AsyncMock()
    monkeypatch.setattr(ctxmod.repos, "release_download", release)
    return release


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
    _stub_claim(monkeypatch)

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
    _stub_claim(monkeypatch)

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
    release = _stub_claim(monkeypatch)

    with pytest.raises(SourceError, match="No soulseek match"):
        await ctx.download_liked_track(7, source="soulseek")
    release.assert_awaited_once()  # claim freed so the track stays retryable


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
async def test_download_liked_track_refused_when_claim_lost(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Losing the DB claim means another process (or click) is already on it."""
    ctx = AppContext(make_settings())
    track = LikedTrack(id=7, spotify_track_id="t1", track_name="A", liked_by="karma")
    monkeypatch.setattr(ctxmod.repos, "get_track_by_id", AsyncMock(return_value=track))
    _stub_claim(monkeypatch, claimed=False)

    with pytest.raises(SourceError, match="already being downloaded"):
        await ctx.download_liked_track(7)


# ---- creating a playlist from the app --------------------------------------


@pytest.mark.asyncio
async def test_create_playlist_persists_with_a_hue(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory: object,
) -> None:
    ctx = AppContext(make_settings())
    ctx.session_factory = db_session_factory  # type: ignore[assignment]
    client = MagicMock()
    client.get_client = AsyncMock(return_value=object())
    ctx.spotify_clients = {"karma": client}
    ctx.owner_label = "karma"
    ctx.default_crew_id = 3
    monkeypatch.setattr(
        ctxmod.spotify_playlist, "create_playlist", AsyncMock(return_value="pl_spotify")
    )

    row = await ctx.create_playlist("Hard Techno")

    assert row.playlist_id == "pl_spotify"
    assert row.genre_key == "hard techno"  # the mapper matches lowercased
    assert row.crew_id == 3
    assert row.hue in ctxmod.PLAYLIST_HUES
    # The name itself becomes an alias, so the resolver can hit the new genre.
    async with ctx.session_factory() as session:  # type: ignore[operator]
        assert await ctxmod.repos.find_genre_key(session, "Hard Techno") == "hard techno"


@pytest.mark.asyncio
async def test_created_playlists_cycle_through_the_hues(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory: object,
) -> None:
    """Hues are persisted and handed out round-robin — two playlists differ."""
    ctx = AppContext(make_settings())
    ctx.session_factory = db_session_factory  # type: ignore[assignment]
    client = MagicMock()
    client.get_client = AsyncMock(return_value=object())
    ctx.spotify_clients = {"karma": client}
    ctx.owner_label = "karma"
    monkeypatch.setattr(
        ctxmod.spotify_playlist,
        "create_playlist",
        AsyncMock(side_effect=lambda _sp, name: f"pl_{name}"),
    )

    first = await ctx.create_playlist("One")
    second = await ctx.create_playlist("Two")

    assert first.hue != second.hue


@pytest.mark.asyncio
async def test_create_playlist_rejects_an_existing_genre(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory: object,
) -> None:
    ctx = AppContext(make_settings())
    ctx.session_factory = db_session_factory  # type: ignore[assignment]
    client = MagicMock()
    client.get_client = AsyncMock(return_value=object())
    ctx.spotify_clients = {"karma": client}
    ctx.owner_label = "karma"
    create = AsyncMock(return_value="pl_x")
    monkeypatch.setattr(ctxmod.spotify_playlist, "create_playlist", create)

    await ctx.create_playlist("Acid")
    create.reset_mock()

    with pytest.raises(SourceError, match="уже есть"):
        await ctx.create_playlist("acid")
    create.assert_not_awaited()  # no orphan playlist left on Spotify


# ---- source health ---------------------------------------------------------


@pytest.mark.asyncio
async def test_source_states_report_health_and_quality(
    make_settings: Callable[..., Settings],
) -> None:
    ctx = AppContext(make_settings())

    class Healthy(FakeSource):
        name = "soulseek"
        quality = "flac и выше"

        async def healthy(self) -> bool:
            return True

    class Down(FakeSource):
        name = "spotify"
        quality = "mp3 320"

        async def healthy(self) -> bool:
            return False

    ctx.sources = {"soulseek": Healthy(), "spotify": Down()}

    states = await ctx.source_states()

    assert states == [
        {"name": "soulseek", "up": True, "quality": "flac и выше"},
        {"name": "spotify", "up": False, "quality": "mp3 320"},
    ]


@pytest.mark.asyncio
async def test_source_health_check_failure_reads_as_down(
    make_settings: Callable[..., Settings],
) -> None:
    """A health probe that raises means the source is unusable, not a 500."""
    ctx = AppContext(make_settings())

    class Exploding(FakeSource):
        name = "soulseek"

        async def healthy(self) -> bool:
            raise ConnectionError("refused")

    ctx.sources = {"soulseek": Exploding()}

    assert (await ctx.source_states())[0]["up"] is False


# ---- playlist batch download ----------------------------------------------


class RefusingSource(MusicSource):
    """A source whose search always fails — nothing to offer."""

    name = "refusing"

    def __init__(self) -> None:
        self.search_calls = 0

    async def search(self, query: str, *, limit: int = 20) -> list[SearchResult]:
        self.search_calls += 1
        raise SourceError("peer unreachable")

    async def download(self, result: SearchResult, dest_dir: Path) -> Path:
        raise SourceError("never reached")


def _batch_track(track_id: int = 7) -> LikedTrack:
    return LikedTrack(
        id=track_id,
        spotify_track_id=f"t{track_id}",
        track_name="Akephale",
        artist_name="ROD",
        liked_by="karma",
    )


def _batch_ctx(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[AppContext, AsyncMock]:
    """Context wired for waterfall tests; returns (ctx, set_download_error mock)."""
    ctx = AppContext(make_settings(download_dir=str(tmp_path)))
    ctx.library = MagicMock()
    monkeypatch.setattr(ctxmod.repos, "get_track_by_id", AsyncMock(return_value=_batch_track()))
    monkeypatch.setattr(ctxmod.repos, "mark_track_downloaded", AsyncMock())
    set_err = AsyncMock()
    monkeypatch.setattr(ctxmod.repos, "set_download_error", set_err)
    _stub_claim(monkeypatch)
    return ctx, set_err


@pytest.mark.asyncio
async def test_any_source_falls_back_in_preference_order(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Lossless sources go first; a failure there falls through to the next one."""
    ctx, set_err = _batch_ctx(make_settings, monkeypatch, tmp_path)
    refusing = RefusingSource()
    fallback = FakeSource()
    ctx.sources = {"spotify": fallback, "soulseek": refusing}

    await ctx.download_track_any_source(7)

    assert refusing.search_calls == 1  # soulseek was tried first…
    assert len(fallback.downloads) == 1  # …spotify caught the fallback
    set_err.assert_not_awaited()


@pytest.mark.asyncio
async def test_any_source_records_error_when_all_fail(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx, set_err = _batch_ctx(make_settings, monkeypatch, tmp_path)
    ctx.sources = {"soulseek": RefusingSource()}

    await ctx.download_track_any_source(7)  # must not raise: the error is recorded

    set_err.assert_awaited_once_with(ANY, 7, "peer unreachable")


@pytest.mark.asyncio
async def test_any_source_skips_already_downloaded_quietly(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A track someone downloaded meanwhile is a no-op, not a recorded failure."""
    ctx, set_err = _batch_ctx(make_settings, monkeypatch, tmp_path)
    fake = FakeSource()
    ctx.sources = {"spotify": fake}
    done = LikedTrack(
        id=7, spotify_track_id="t7", liked_by="karma", downloaded_at=datetime(2026, 7, 1)
    )
    monkeypatch.setattr(ctxmod.repos, "get_track_by_id", AsyncMock(return_value=done))

    await ctx.download_track_any_source(7)

    assert fake.downloads == []
    set_err.assert_not_awaited()


@pytest.mark.asyncio
async def test_playlist_download_runs_every_track_despite_failures(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    """One broken track must not stop the rest of the batch."""
    ctx = AppContext(make_settings())
    tracks = [_batch_track(1), _batch_track(2)]
    monkeypatch.setattr(ctxmod.repos, "list_playlist_tracks", AsyncMock(return_value=tracks))
    calls: list[int] = []

    async def record(track_id: int) -> None:
        calls.append(track_id)
        if track_id == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(ctx, "download_track_any_source", record)

    queued = await ctx.start_playlist_download(3, "pl_x")
    await ctx._playlist_tasks[3]  # noqa: SLF001 — wait out the background worker

    assert queued == 2
    assert calls == [1, 2]


@pytest.mark.asyncio
async def test_playlist_download_single_flight_per_playlist(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AppContext(make_settings())
    monkeypatch.setattr(
        ctxmod.repos, "list_playlist_tracks", AsyncMock(return_value=[_batch_track(1)])
    )
    gate = asyncio.Event()

    async def blocked(track_id: int) -> None:
        await gate.wait()

    monkeypatch.setattr(ctx, "download_track_any_source", blocked)

    await ctx.start_playlist_download(3, "pl_x")
    with pytest.raises(SourceError, match="already running"):
        await ctx.start_playlist_download(3, "pl_x")

    gate.set()
    await ctx._playlist_tasks[3]  # noqa: SLF001
    # Finished — the same playlist can be downloaded again.
    assert await ctx.start_playlist_download(3, "pl_x") == 1
    await ctx._playlist_tasks[3]  # noqa: SLF001


@pytest.mark.asyncio
async def test_playlist_download_with_nothing_to_do(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AppContext(make_settings())
    monkeypatch.setattr(ctxmod.repos, "list_playlist_tracks", AsyncMock(return_value=[]))

    assert await ctx.start_playlist_download(3, "pl_x") == 0
    assert 3 not in ctx._playlist_tasks  # noqa: SLF001 — no idle task left behind


# ---- bootstrap: clients from the users table --------------------------------


@pytest.mark.asyncio
async def test_bootstrap_builds_clients_from_users_table(
    make_settings: Callable[..., Settings],
    db_session_factory: object,
) -> None:
    """Clients cover every user row — including ones added after first seed."""
    ctx = AppContext(make_settings())
    ctx.session_factory = db_session_factory  # type: ignore[assignment]
    async with ctx.session_factory() as session:  # type: ignore[operator]
        await ctxmod.repos.ensure_user(session, label="egor", display_name="Егор")

    await ctx.bootstrap()

    assert set(ctx.spotify_clients) == {"karma", "stress303", "egor"}
    assert ctx.owner_label == "karma"
    assert ctx.default_crew_id is not None
    assert ctx.owner_client() is ctx.spotify_clients["karma"]


def test_owner_client_before_bootstrap_refuses(
    make_settings: Callable[..., Settings],
) -> None:
    from src.spotify.client import NotAuthorizedError

    ctx = AppContext(make_settings())
    with pytest.raises(NotAuthorizedError):
        ctx.owner_client()


# ---- default playlists init ------------------------------------------------


@pytest.mark.asyncio
async def test_init_default_playlists_creates_missing_and_seeds_aliases(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory: object,
) -> None:
    ctx = AppContext(make_settings())
    ctx.session_factory = db_session_factory  # type: ignore[assignment] — real SQLite
    sp = object()
    client = MagicMock()
    client.get_client = AsyncMock(return_value=sp)
    ctx.spotify_clients = {"karma": client}
    ctx.owner_label = "karma"
    ctx.default_crew_id = 7
    create = AsyncMock(side_effect=lambda _sp, name: f"pl_{name.lower()}")
    monkeypatch.setattr(ctxmod.spotify_playlist, "create_playlist", create)

    result = await ctx.init_default_playlists()

    assert result["created"] == len(ctxmod.DEFAULT_PLAYLISTS)
    assert result["skipped"] == 0
    async with ctx.session_factory() as session:  # type: ignore[operator]
        playlists = await ctxmod.repos.get_all_playlists(session)
        assert {p.genre_key for p in playlists} == {k for k, _, _ in ctxmod.DEFAULT_PLAYLISTS}
        assert {p.crew_id for p in playlists} == {7}  # crew playlists, not orphans
        # The mapper must resolve a documented alias right after init.
        assert await ctxmod.repos.find_genre_key(session, "dark techno") == "hardgroove"


@pytest.mark.asyncio
async def test_init_default_playlists_is_idempotent(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory: object,
) -> None:
    """A second run creates nothing — and needs no Spotify auth at all."""
    ctx = AppContext(make_settings())
    ctx.session_factory = db_session_factory  # type: ignore[assignment]
    client = MagicMock()
    client.get_client = AsyncMock(return_value=object())
    ctx.spotify_clients = {"karma": client}
    ctx.owner_label = "karma"
    create = AsyncMock(side_effect=lambda _sp, name: f"pl_{name.lower()}")
    monkeypatch.setattr(ctxmod.spotify_playlist, "create_playlist", create)

    await ctx.init_default_playlists()
    client.get_client = AsyncMock(side_effect=AssertionError("must not need Spotify"))

    result = await ctx.init_default_playlists()

    assert result["created"] == 0
    assert result["skipped"] == len(ctxmod.DEFAULT_PLAYLISTS)


@pytest.mark.asyncio
async def test_init_default_playlists_requires_auth_only_when_creating(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory: object,
) -> None:
    from src.spotify.client import NotAuthorizedError

    ctx = AppContext(make_settings())
    ctx.session_factory = db_session_factory  # type: ignore[assignment]
    client = MagicMock()
    client.get_client = AsyncMock(side_effect=NotAuthorizedError("karma is not connected"))
    ctx.spotify_clients = {"karma": client}
    ctx.owner_label = "karma"

    with pytest.raises(NotAuthorizedError):
        await ctx.init_default_playlists()

    # Nothing half-created before the auth failure surfaced.
    async with ctx.session_factory() as session:  # type: ignore[operator]
        assert await ctxmod.repos.get_all_playlists(session) == []


@pytest.mark.asyncio
async def test_aclose_cancels_running_playlist_downloads(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AppContext(make_settings())
    monkeypatch.setattr(
        ctxmod.repos, "list_playlist_tracks", AsyncMock(return_value=[_batch_track(1)])
    )
    started = asyncio.Event()

    async def hang(track_id: int) -> None:
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(ctx, "download_track_any_source", hang)

    await ctx.start_playlist_download(3, "pl_x")
    await asyncio.wait_for(started.wait(), timeout=5)
    await ctx.aclose()

    assert ctx._playlist_tasks[3].cancelled()  # noqa: SLF001
