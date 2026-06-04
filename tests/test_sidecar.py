"""Tests for the FastAPI sidecar routes (with a mocked AppContext)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import src.sidecar.app as appmod
from src.db.models import LikedTrack
from src.sidecar.app import create_app


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
    from src.sources.base import SearchResult

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
