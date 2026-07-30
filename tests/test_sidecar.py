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
    ctx.settings.allowed_origins.return_value = ["http://localhost:5173"]
    ctx.settings.sidecar_auth_token = ""  # origin-filter mode unless a test opts in
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


def _real_move(add_mock: AsyncMock):
    """move_track with its real remove-then-add logic over the patched pieces."""

    async def _move(sp, track_id, *, from_playlist, to_playlist):
        if from_playlist and from_playlist != to_playlist:
            await appmod.spotify_playlist.remove_track_from_playlist(sp, from_playlist, track_id)
        return await add_mock(sp, to_playlist, track_id)

    return _move


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
    monkeypatch.setattr(appmod.spotify_playlist, "move_track", _real_move(add_mock))
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


# ---- origin guard ---------------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        ("http://localhost:5173", True),  # Vite dev server
        ("null", True),  # packaged renderer loaded from file://
        ("https://evil.example", False),  # drive-by from a random browser tab
    ],
)
def test_origin_guard(origin: str, allowed: bool) -> None:
    ctx = _make_ctx()
    with _client(ctx) as c:
        r = c.post("/likes/fetch", headers={"Origin": origin})
    assert (r.status_code == 200) is allowed
    if not allowed:
        assert r.status_code == 403


def test_no_origin_header_is_allowed() -> None:
    """Non-browser clients (curl, scripts driving the API directly)."""
    with _client(_make_ctx()) as c:
        r = c.post("/likes/fetch")
    assert r.status_code == 200


def test_assign_moves_track_between_playlists(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-assigning must remove the track from the old Spotify playlist —
    otherwise it stays in both while the DB records only the new one."""
    ctx, add_mock, _assign_mock, sp = _assign_ctx(monkeypatch)
    assigned = LikedTrack(
        id=7,
        spotify_track_id="t1",
        liked_by="karma",
        assigned_playlist_id="pl_old",
    )
    monkeypatch.setattr(appmod.repos, "get_track_by_id", AsyncMock(return_value=assigned))
    remove_mock = AsyncMock()
    monkeypatch.setattr(appmod.spotify_playlist, "remove_track_from_playlist", remove_mock)

    with _client(ctx) as c:
        r = c.post("/tracks/7/assign", json={"playlist_db_id": 99})

    assert r.status_code == 200
    remove_mock.assert_awaited_once_with(sp, "pl_old", "t1")
    add_mock.assert_awaited_once_with(sp, "pl_spotify_id", "t1")


def test_assign_to_same_playlist_does_not_remove(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx, _add_mock, _assign_mock, _sp = _assign_ctx(monkeypatch)
    assigned = LikedTrack(
        id=7,
        spotify_track_id="t1",
        liked_by="karma",
        assigned_playlist_id="pl_spotify_id",  # already there
    )
    monkeypatch.setattr(appmod.repos, "get_track_by_id", AsyncMock(return_value=assigned))
    remove_mock = AsyncMock()
    monkeypatch.setattr(appmod.spotify_playlist, "remove_track_from_playlist", remove_mock)

    with _client(ctx) as c:
        c.post("/tracks/7/assign", json={"playlist_db_id": 99})

    remove_mock.assert_not_awaited()


# ---- token auth -----------------------------------------------------------


def _token_ctx() -> MagicMock:
    ctx = _make_ctx()
    ctx.settings.sidecar_auth_token = "s3cret"
    return ctx


def test_token_required_when_configured() -> None:
    with _client(_token_ctx()) as c:
        r = c.post("/likes/fetch")
    assert r.status_code == 401


def test_valid_token_accepted() -> None:
    with _client(_token_ctx()) as c:
        r = c.post("/likes/fetch", headers={"X-Aux-Token": "s3cret"})
    assert r.status_code == 200


def test_token_beats_a_forged_null_origin() -> None:
    """A sandboxed iframe on any site presents Origin: null — the token is what
    actually keeps it out."""
    with _client(_token_ctx()) as c:
        r = c.post("/likes/fetch", headers={"Origin": "null"})
    assert r.status_code == 401


def test_health_stays_open_for_the_liveness_probe() -> None:
    with _client(_token_ctx()) as c:
        r = c.get("/health")
    assert r.status_code == 200


def test_preflight_with_null_origin_and_token_header() -> None:
    """The packaged renderer (Origin: null) sends preflighted requests because
    of X-Aux-Token — CORS must answer them or the browser blocks everything."""
    with _client(_token_ctx()) as c:
        r = c.options(
            "/likes/fetch",
            headers={
                "Origin": "null",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-aux-token",
            },
        )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin")


def test_preflight_with_null_origin_without_token_mode() -> None:
    """Same preflight must work in origin-filter mode: 'null' is in the CORS list."""
    with _client(_make_ctx()) as c:
        r = c.options(
            "/likes/fetch",
            headers={"Origin": "null", "Access-Control-Request-Method": "POST"},
        )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "null"


def test_token_accepted_via_query_param() -> None:
    """<audio src> cannot set headers — the audio route takes the token as query."""
    with _client(_token_ctx()) as c:
        r = c.post("/likes/fetch?token=s3cret")
    assert r.status_code == 200


def test_track_audio_serves_downloaded_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = tmp_path / "akephale.mp3"
    audio.write_bytes(b"ID3audio")
    downloaded = LikedTrack(
        id=7, spotify_track_id="t1", liked_by="karma", download_path=str(audio)
    )
    ctx = _make_ctx()
    monkeypatch.setattr(appmod.repos, "get_track_by_id", AsyncMock(return_value=downloaded))

    with _client(ctx) as c:
        r = c.get("/tracks/7/audio")

    assert r.status_code == 200
    assert r.content == b"ID3audio"


def test_track_audio_404_when_not_downloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _make_ctx()
    monkeypatch.setattr(appmod.repos, "get_track_by_id", AsyncMock(return_value=_TRACK))

    with _client(ctx) as c:
        r = c.get("/tracks/7/audio")
    assert r.status_code == 404
