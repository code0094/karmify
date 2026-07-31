"""Tests for the FastAPI sidecar routes (with a mocked AppContext)."""

from datetime import datetime
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
    ctx.settings.allowed_hosts.return_value = ["127.0.0.1", "karmify.example"]
    return ctx


def _client(ctx: MagicMock):
    from fastapi.testclient import TestClient

    # base_url must be a trusted host: TrustedHostMiddleware rejects the rest.
    return TestClient(create_app(ctx), base_url="http://127.0.0.1")


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


def test_list_playlists_includes_download_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.db.repos import PlaylistDownloadStats

    ctx = _make_ctx()
    monkeypatch.setattr(appmod.repos, "get_all_playlists", AsyncMock(return_value=[_PLAYLIST]))
    monkeypatch.setattr(
        appmod.repos,
        "playlist_download_stats",
        AsyncMock(
            return_value={
                "pl_spotify_id": PlaylistDownloadStats(
                    total=4, downloaded=2, downloading=1, failed=1
                )
            }
        ),
    )

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
            "total_tracks": 4,
            "downloaded": 2,
            "downloading": 1,
            "failed": 1,
        }
    ]


def test_list_playlists_zero_stats_without_tracks(monkeypatch: pytest.MonkeyPatch) -> None:
    """A playlist with no assigned tracks simply reports zeros."""
    ctx = _make_ctx()
    monkeypatch.setattr(appmod.repos, "get_all_playlists", AsyncMock(return_value=[_PLAYLIST]))
    monkeypatch.setattr(appmod.repos, "playlist_download_stats", AsyncMock(return_value={}))

    with _client(ctx) as c:
        r = c.get("/playlists")

    assert r.json()[0]["total_tracks"] == 0
    assert r.json()[0]["downloaded"] == 0


def test_download_playlist_starts_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _make_ctx()
    monkeypatch.setattr(appmod.repos, "get_playlist_by_id", AsyncMock(return_value=_PLAYLIST))
    ctx.start_playlist_download = AsyncMock(return_value=5)

    with _client(ctx) as c:
        r = c.post("/playlists/3/download")

    assert r.status_code == 202  # accepted: the work continues in the background
    assert r.json() == {"queued": 5}
    # The Spotify playlist id is what the tracks are keyed by — not the DB pk.
    ctx.start_playlist_download.assert_awaited_once_with(3, "pl_spotify_id")


def test_download_playlist_unknown_404(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _make_ctx()
    monkeypatch.setattr(appmod.repos, "get_playlist_by_id", AsyncMock(return_value=None))

    with _client(ctx) as c:
        r = c.post("/playlists/99/download")
    assert r.status_code == 404


def test_download_playlist_already_running_409(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.sources.base import DownloadInFlightError

    ctx = _make_ctx()
    monkeypatch.setattr(appmod.repos, "get_playlist_by_id", AsyncMock(return_value=_PLAYLIST))
    ctx.start_playlist_download = AsyncMock(side_effect=DownloadInFlightError("already running"))

    with _client(ctx) as c:
        r = c.post("/playlists/3/download")
    assert r.status_code == 409


def test_init_playlists_reports_counts() -> None:
    ctx = _make_ctx()
    ctx.init_default_playlists = AsyncMock(return_value={"created": 5, "skipped": 0})

    with _client(ctx) as c:
        r = c.post("/playlists/init")

    assert r.status_code == 200
    assert r.json() == {"created": 5, "skipped": 0}


def test_init_playlists_maps_missing_auth_to_400() -> None:
    from src.spotify.client import NotAuthorizedError

    ctx = _make_ctx()
    ctx.init_default_playlists = AsyncMock(
        side_effect=NotAuthorizedError("Spotify account 'karma' is not connected")
    )

    with _client(ctx) as c:
        r = c.post("/playlists/init")

    assert r.status_code == 400
    assert "not connected" in r.json()["detail"]


def test_tracks_expose_download_progress_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """The renderer derives ⏳/❌ badges from these two fields."""
    ctx = _make_ctx()
    track = LikedTrack(
        id=1,
        spotify_track_id="t1",
        liked_by="karma",
        download_started_at=datetime(2026, 7, 30, 12, 0),
        last_download_error="peer unreachable",
    )
    monkeypatch.setattr(appmod.repos, "list_tracks", AsyncMock(return_value=[track]))

    with _client(ctx) as c:
        r = c.get("/tracks")

    data = r.json()[0]
    assert data["download_started_at"] is not None
    assert data["last_download_error"] == "peer unreachable"


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


def test_query_token_rejected_outside_audio_route() -> None:
    """URLs land in access logs — the query fallback is for <audio> only."""
    with _client(_token_ctx()) as c:
        r = c.post("/likes/fetch?token=s3cret")
    assert r.status_code == 401


def test_query_token_accepted_on_audio_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """<audio src> cannot set headers — the audio route takes the token as query."""
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    downloaded = LikedTrack(
        id=7, spotify_track_id="t1", liked_by="karma", download_path=str(audio)
    )
    monkeypatch.setattr(appmod.repos, "get_track_by_id", AsyncMock(return_value=downloaded))

    with _client(_token_ctx()) as c:
        assert c.get("/tracks/7/audio?token=s3cret").status_code == 200
        assert c.get("/tracks/7/audio").status_code == 401


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


def test_untrusted_host_rejected() -> None:
    """DNS rebinding sends same-origin requests with no Origin — but the Host
    header still names the attacker's domain."""
    with _client(_make_ctx()) as c:
        r = c.get("/health", headers={"host": "evil.example"})
    assert r.status_code == 400


def test_configured_public_host_accepted() -> None:
    """Behind a reverse proxy the Host is the public name, not the bind address."""
    with _client(_make_ctx()) as c:
        r = c.get("/health", headers={"host": "karmify.example"})
    assert r.status_code == 200


def test_tracks_limit_bounds() -> None:
    with _client(_make_ctx()) as c:
        assert c.get("/tracks?limit=0").status_code == 422
        assert c.get("/tracks?limit=100000").status_code == 422


def test_zotify_failure_maps_to_502() -> None:
    """DownloadError is a SourceError: zotify failures must not bubble as 500."""
    from src.spotify.downloader import DownloadError

    ctx = _make_ctx()
    ctx.download_liked_track = AsyncMock(side_effect=DownloadError("zotify не найден в PATH"))

    with _client(ctx) as c:
        r = c.post("/tracks/5/download", json={"source": "spotify"})
    assert r.status_code == 502
    assert "zotify" in r.json()["detail"]


def test_non_ascii_token_is_rejected_not_crashing() -> None:
    """str compare_digest requires ASCII — a 0xFF header byte must 401, not 500."""
    with _client(_token_ctx()) as c:
        r = c.post("/likes/fetch", headers={b"x-aux-token": b"\xff\xfe"})
    assert r.status_code == 401


# ---- spotify authorization -------------------------------------------------


def _auth_ctx(monkeypatch: pytest.MonkeyPatch, token: str = "") -> MagicMock:
    ctx = _make_ctx()
    ctx.settings.sidecar_auth_token = token
    ctx.spotify_clients = {"karma": MagicMock(), "stress303": MagicMock()}
    ctx.auth_flow = MagicMock()
    ctx.auth_flow.start.return_value = "https://accounts.spotify.com/authorize?state=abc"
    ctx.auth_flow.redeem.return_value = ("karma", {"access_token": "a", "refresh_token": "r"})
    ctx.store_tokens = AsyncMock()
    return ctx


def test_login_redirects_to_spotify(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _auth_ctx(monkeypatch)
    with _client(ctx) as c:
        r = c.get("/auth/spotify/login?user=karma", follow_redirects=False)

    assert r.status_code == 307
    assert r.headers["location"].startswith("https://accounts.spotify.com/authorize")
    ctx.auth_flow.start.assert_called_once_with("karma")


def test_login_rejects_unknown_account(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _auth_ctx(monkeypatch)
    with _client(ctx) as c:
        r = c.get("/auth/spotify/login?user=stranger", follow_redirects=False)
    assert r.status_code == 404


def test_login_needs_the_token_when_one_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """A browser navigates here, so the token rides in the query string."""
    ctx = _auth_ctx(monkeypatch, token="s3cret")
    with _client(ctx) as c:
        assert c.get("/auth/spotify/login?user=karma").status_code == 401
        ok = c.get("/auth/spotify/login?user=karma&token=s3cret", follow_redirects=False)
    assert ok.status_code == 307


def test_callback_stores_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _auth_ctx(monkeypatch, token="s3cret")  # reachable without the token
    with _client(ctx) as c:
        r = c.get("/auth/spotify/callback?code=xyz&state=abc")

    assert r.status_code == 200
    assert "karma" in r.text
    ctx.auth_flow.redeem.assert_called_once_with(code="xyz", state="abc")
    ctx.store_tokens.assert_awaited_once()


def test_callback_rejects_bad_state(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.spotify.oauth import OAuthError

    ctx = _auth_ctx(monkeypatch)
    ctx.auth_flow.redeem.side_effect = OAuthError("Unknown or expired authorization request")

    with _client(ctx) as c:
        r = c.get("/auth/spotify/callback?code=xyz&state=forged")

    assert r.status_code == 400
    ctx.store_tokens.assert_not_awaited()


def test_callback_reports_user_denial(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _auth_ctx(monkeypatch)
    with _client(ctx) as c:
        r = c.get("/auth/spotify/callback?error=access_denied")
    assert r.status_code == 400
    assert "access_denied" in r.text
    ctx.store_tokens.assert_not_awaited()


def test_status_lists_connected_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _auth_ctx(monkeypatch)
    accounts = {"karma": object(), "stress303": None}
    monkeypatch.setattr(
        appmod.repos, "get_account", AsyncMock(side_effect=lambda _s, label: accounts[label])
    )

    with _client(ctx) as c:
        r = c.get("/auth/spotify/status")

    assert r.json() == {"karma": True, "stress303": False}
