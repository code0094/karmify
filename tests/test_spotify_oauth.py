"""Tests for the browser authorization flow that replaces pasted refresh tokens."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.config import Settings
from src.spotify.oauth import OAuthError, SpotifyAuthFlow


def _flow(make_settings: Callable[..., Settings], **overrides: Any) -> SpotifyAuthFlow:
    return SpotifyAuthFlow(make_settings(**overrides))


def _stub_oauth(flow: SpotifyAuthFlow, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    oauth = MagicMock()
    oauth.get_authorize_url.side_effect = lambda state: (
        f"https://accounts.spotify.com/authorize?state={state}"
    )
    monkeypatch.setattr(flow, "_oauth", lambda: oauth)
    return oauth


def test_start_returns_url_carrying_the_state(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    flow = _flow(make_settings)
    _stub_oauth(flow, monkeypatch)

    url = flow.start("karma")

    assert url.startswith("https://accounts.spotify.com/authorize?state=")
    assert len(flow._pending) == 1


def test_redeem_returns_user_and_tokens(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    flow = _flow(make_settings)
    oauth = _stub_oauth(flow, monkeypatch)
    oauth.get_access_token.return_value = {
        "access_token": "acc",
        "refresh_token": "ref",
        "expires_in": 3600,
    }
    state = flow.start("stress303").split("state=")[1]

    user, tokens = flow.redeem(code="the-code", state=state)

    assert user == "stress303"
    assert tokens["refresh_token"] == "ref"
    oauth.get_access_token.assert_called_once_with("the-code", as_dict=True, check_cache=False)


def test_state_is_single_use(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A replayed callback must not re-authorize the account."""
    flow = _flow(make_settings)
    oauth = _stub_oauth(flow, monkeypatch)
    oauth.get_access_token.return_value = {
        "access_token": "a",
        "refresh_token": "r",
        "expires_in": 60,
    }
    state = flow.start("karma").split("state=")[1]
    flow.redeem(code="c", state=state)

    with pytest.raises(OAuthError, match="Unknown or expired"):
        flow.redeem(code="c", state=state)


def test_forged_state_is_rejected(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The callback is reachable without a token — state is what guards it."""
    flow = _flow(make_settings)
    _stub_oauth(flow, monkeypatch)
    flow.start("karma")

    with pytest.raises(OAuthError, match="Unknown or expired"):
        flow.redeem(code="c", state="made-up")


def test_expired_state_is_rejected(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.spotify.oauth as oauth_mod

    flow = _flow(make_settings)
    _stub_oauth(flow, monkeypatch)
    state = flow.start("karma").split("state=")[1]

    monkeypatch.setattr(oauth_mod.time, "monotonic", lambda: 10**6)

    with pytest.raises(OAuthError, match="Unknown or expired"):
        flow.redeem(code="c", state=state)


def test_missing_refresh_token_is_an_error(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a refresh token the account would break at the next expiry."""
    flow = _flow(make_settings)
    oauth = _stub_oauth(flow, monkeypatch)
    oauth.get_access_token.return_value = {"access_token": "a", "expires_in": 60}
    state = flow.start("karma").split("state=")[1]

    with pytest.raises(OAuthError, match="refresh token"):
        flow.redeem(code="c", state=state)


def test_unconfigured_app_fails_before_minting_state(
    make_settings: Callable[..., Settings],
) -> None:
    flow = _flow(make_settings, spotify_client_id="", spotify_client_secret="")

    with pytest.raises(OAuthError, match="not configured"):
        flow.start("karma")
    assert not flow._pending
