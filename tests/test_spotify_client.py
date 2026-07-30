"""Tests for SpotifyClient: DB-backed token reuse and refresh."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.spotify.client as clientmod
from src.config import Settings
from src.db.models import SpotifyAccount
from src.spotify.client import SpotifyClient


class FakeSpotify:
    """Captures the auth token spotipy.Spotify would be created with."""

    def __init__(self, auth: str) -> None:
        self.auth = auth


def _account(*, expires_in_hours: float, token: str = "db-access") -> SpotifyAccount:
    return SpotifyAccount(
        id=1,
        user_label="karma",
        spotify_user_id="sp-user",
        access_token=token,
        refresh_token="db-refresh",
        token_expires_at=datetime.now(tz=UTC) + timedelta(hours=expires_in_hours),
    )


@pytest.fixture
def client(
    make_settings: Callable[..., Settings],
    mock_session_factory: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> SpotifyClient:
    monkeypatch.setattr(clientmod.spotipy, "Spotify", FakeSpotify)
    return SpotifyClient("karma", make_settings(), mock_session_factory)


@pytest.mark.asyncio
async def test_valid_db_token_is_reused(
    client: SpotifyClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        clientmod.repos, "get_account", AsyncMock(return_value=_account(expires_in_hours=1))
    )
    refresh = AsyncMock()
    monkeypatch.setattr(clientmod.repos, "update_tokens", refresh)

    sp = await client.get_client()

    assert sp.auth == "db-access"  # type: ignore[attr-defined]
    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_db_token_triggers_refresh(
    client: SpotifyClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        clientmod.repos, "get_account", AsyncMock(return_value=_account(expires_in_hours=-1))
    )
    update = AsyncMock()
    monkeypatch.setattr(clientmod.repos, "update_tokens", update)

    seen: dict[str, Any] = {}

    def fake_refresh(refresh_token: str) -> dict[str, Any]:
        seen["refresh_token"] = refresh_token
        return {"access_token": "fresh", "expires_in": 3600}

    monkeypatch.setattr(client._oauth, "refresh_access_token", fake_refresh)

    sp = await client.get_client()

    assert sp.auth == "fresh"  # type: ignore[attr-defined]
    assert seen["refresh_token"] == "db-refresh"  # DB token wins over settings
    update.assert_awaited_once()
    kwargs = update.await_args.kwargs
    assert kwargs["access_token"] == "fresh"
    # Spotify did not rotate the refresh token — the old one must be kept.
    assert kwargs["refresh_token"] == "db-refresh"


@pytest.mark.asyncio
async def test_no_account_falls_back_to_settings_token(
    client: SpotifyClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(clientmod.repos, "get_account", AsyncMock(return_value=None))
    update = AsyncMock()
    monkeypatch.setattr(clientmod.repos, "update_tokens", update)

    seen: dict[str, Any] = {}

    def fake_refresh(refresh_token: str) -> dict[str, Any]:
        seen["refresh_token"] = refresh_token
        return {"access_token": "first", "expires_in": 3600, "refresh_token": "rotated"}

    monkeypatch.setattr(client._oauth, "refresh_access_token", fake_refresh)

    sp = await client.get_client()

    assert sp.auth == "first"  # type: ignore[attr-defined]
    assert seen["refresh_token"] == "rt-karma"  # from Settings (conftest)
    # Spotify ROTATED the refresh token — losing it would kill the account:
    # the rotated value, not the input one, must be persisted.
    update.assert_awaited_once()
    assert update.await_args.kwargs["refresh_token"] == "rotated"


def test_unknown_user_label_raises(
    make_settings: Callable[..., Settings], mock_session_factory: MagicMock
) -> None:
    c = SpotifyClient("nobody", make_settings(), mock_session_factory)
    with pytest.raises(ValueError, match="nobody"):
        c._get_refresh_token()
