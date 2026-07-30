"""Tests for the FastAPI sidecar routes (with a mocked AppContext)."""

from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

import src.sidecar.app as appmod
from src.db.models import GenrePlaylist, LikedTrack
from src.sidecar.app import create_app
from src.sources.base import SearchResult


def _make_ctx() -> MagicMock:
    """Build a mock AppContext with an async-context-manager session_factory."""
    ctx = MagicMock()
    ctx.sources = {"spotify": object(), "soulseek": object()}
    ctx.aclose = AsyncMock()

    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    ctx.session_factory = factory

    ctx.fetch_likes = AsyncMock(return_value=3)
    return ctx


def _client(ctx: MagicMock):
    from fastapi.testclient import TestClient

    return TestClient(create_app(ctx))


def test_health_lists_sources() -> None:
    with _client(_make_ctx()) as c:
        r = c.get("/health")
    assert r.status_code == 200
    assert set(r.json()["sources"]) == {"spotify", "soulseek"}


def test_fetch_likes_returns_count() -> None:
    with _client(_make_ctx()) as c:
        r = c.post("/likes/fetch")
    assert r.status_code == 200
    assert r.json() == {"new": 3}


def test_list_tracks(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _make_ctx()
    track = LikedTrack(
        id=1,
        spotify_track_id="t1",
        track_name="Akephale",
        artist_name="ROD",
        liked_by="karma",
    )

    async def fake_list_tracks(_session, **_kwargs):
        return [track]

    monkeypatch.setattr(appmod.repos, "list_tracks", fake_list_tracks)

    with _client(ctx) as c:
        r = c.get("/tracks")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["spotify_track_id"] == "t1"
    assert data[0]["downloaded_at"] is None


def test_download_track_maps_source_error() -> None:
    from src.sources.base import SourceError

    ctx = _make_ctx()
    ctx.download_liked_track = AsyncMock(side_effect=SourceError("boom"))

    with _client(ctx) as c:
        r = c.post("/tracks/5/download", json={"source": "spotify"})
    assert r.status_code == 502
    assert "boom" in r.json()["detail"]


def test_sources_search() -> None:
    ctx = _make_ctx()
    ctx.search_sources = AsyncMock(
        return_value=[
            SearchResult(
                source="soulseek",
                title="t",
                artist="a",
                download_ref="u|f.flac",
                audio_format="flac",
            )
        ]
    )

    with _client(ctx) as c:
        r = c.post("/sources/search", json={"query": "x", "source": "soulseek"})
    assert r.status_code == 200
    assert r.json()[0]["audio_format"] == "flac"


# ---- /tracks/{id}/assign --------------------------------------------------


# Shared read-only fixtures: tests must never mutate these (shared identity
# would silently leak between tests) — build a fresh object instead.
_TRACK = LikedTrack(id=7, spotify_track_id="t1", track_name="Akephale", liked_by="karma")
_PLAYLIST = GenrePlaylist(
    id=3, genre_key="acid", playlist_id="pl_spotify_id", display_name="Acid", emoji="🧪"
)


def _assign_ctx(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, AsyncMock, AsyncMock, object]:
    """Context wired for the assign happy path; returns (ctx, add_mock, assign_mock, sp)."""
    ctx = _make_ctx()
    sp = object()
    client = MagicMock()
    client.get_client = AsyncMock(return_value=sp)
    ctx.spotify_clients = {"karma": client}  # real dict: .get() must be able to miss

    monkeypatch.setattr(appmod.repos, "get_track_by_id", AsyncMock(return_value=_TRACK))
    monkeypatch.setattr(appmod.repos, "get_playlist_by_id", AsyncMock(return_value=_PLAYLIST))
    add_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(appmod.spotify_playlist, "add_track_to_playlist", add_mock)
    assign_mock = AsyncMock()
    monkeypatch.setattr(appmod.repos, "assign_track_to_playlist", assign_mock)
    return ctx, add_mock, assign_mock, sp


def test_assign_track_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _make_ctx()
    monkeypatch.setattr(appmod.repos, "get_track_by_id", AsyncMock(return_value=None))

    with _client(ctx) as c:
        r = c.post("/tracks/5/assign", json={"playlist_db_id": 3})
    assert r.status_code == 404


def test_assign_playlist_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _make_ctx()
    monkeypatch.setattr(appmod.repos, "get_track_by_id", AsyncMock(return_value=_TRACK))
    monkeypatch.setattr(appmod.repos, "get_playlist_by_id", AsyncMock(return_value=None))

    with _client(ctx) as c:
        r = c.post("/tracks/7/assign", json={"playlist_db_id": 99})
    assert r.status_code == 404


def test_assign_no_spotify_client_for_user(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx, *_ = _assign_ctx(monkeypatch)
    ctx.spotify_clients = {}

    with _client(ctx) as c:
        r = c.post("/tracks/7/assign", json={"playlist_db_id": 3})
    assert r.status_code == 400


def test_assign_happy_path_passes_spotify_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx, add_mock, assign_mock, sp = _assign_ctx(monkeypatch)

    with _client(ctx) as c:
        # 99 != _PLAYLIST.id on purpose: the DB pk itself must never be forwarded.
        r = c.post("/tracks/7/assign", json={"playlist_db_id": 99})

    assert r.status_code == 200
    assert r.json() == {"added": True}
    # The Spotify playlist id and track id go to Spotify — not the DB pk.
    add_mock.assert_awaited_once_with(sp, "pl_spotify_id", "t1")
    assign_mock.assert_awaited_once_with(ANY, 7, "pl_spotify_id", "karma")


def test_assign_duplicate_still_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    """Characterization of intended convergence: Spotify already has the track
    (added=False), but the DB assignment is written anyway so local state
    matches reality."""
    ctx, add_mock, assign_mock, _sp = _assign_ctx(monkeypatch)
    add_mock.return_value = False

    with _client(ctx) as c:
        r = c.post("/tracks/7/assign", json={"playlist_db_id": 3})

    assert r.json() == {"added": False}
    assign_mock.assert_awaited_once()


# ---- remaining routes -----------------------------------------------------


def test_download_track_happy_path() -> None:
    ctx = _make_ctx()
    ctx.download_liked_track = AsyncMock(return_value=Path("akephale.mp3"))

    with _client(ctx) as c:
        r = c.post("/tracks/9/download", json={"source": "soulseek"})

    assert r.status_code == 200
    assert r.json() == {"path": "akephale.mp3"}
    ctx.download_liked_track.assert_awaited_once_with(9, source="soulseek")


def test_sources_download_parses_result() -> None:
    ctx = _make_ctx()
    ctx.download_result = AsyncMock(return_value=Path("x.flac"))
    body = {
        "result": {
            "source": "soulseek",
            "title": "t",
            "artist": "a",
            "download_ref": "u|f.flac",
            "audio_format": "flac",
        }
    }

    with _client(ctx) as c:
        r = c.post("/sources/download", json=body)

    assert r.status_code == 200
    assert r.json() == {"path": "x.flac"}
    (arg,) = ctx.download_result.await_args.args
    assert isinstance(arg, SearchResult)  # parsed model, not a raw dict
    assert arg.download_ref == "u|f.flac"
    assert arg.source == "soulseek"


def test_list_tracks_passes_query_params(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _make_ctx()
    seen: dict[str, object] = {}

    async def fake_list_tracks(_session, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(appmod.repos, "list_tracks", fake_list_tracks)

    with _client(ctx) as c:
        r = c.get("/tracks?genre=acid&liked_by=karma&only_undownloaded=true&limit=5")

    assert r.status_code == 200
    assert seen == {"genre": "acid", "liked_by": "karma", "only_undownloaded": True, "limit": 5}


def test_list_playlists(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _make_ctx()
    monkeypatch.setattr(appmod.repos, "get_all_playlists", AsyncMock(return_value=[_PLAYLIST]))

    with _client(ctx) as c:
        r = c.get("/playlists")

    assert r.status_code == 200
    assert r.json() == [
        {
            "id": 3,
            "genre_key": "acid",
            "playlist_id": "pl_spotify_id",
            "display_name": "Acid",
            "emoji": "🧪",
        }
    ]


def test_lifespan_closes_context() -> None:
    ctx = _make_ctx()
    with _client(ctx):
        pass
    ctx.aclose.assert_awaited_once()
