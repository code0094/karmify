"""Tests for Settings: optional credential groups and entrypoint guards."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from src.config import Settings


def test_settings_load_without_telegram(make_settings: Callable[..., Settings]) -> None:
    """The sidecar must boot without any Telegram credentials configured."""
    s = make_settings()
    assert s.telegram_bot_token == ""
    assert s.telegram_chat_id == 0


def test_settings_accept_telegram_when_provided(
    make_settings: Callable[..., Settings],
) -> None:
    s = make_settings(telegram_bot_token="123:abc", telegram_chat_id=-1001234567890)
    assert s.telegram_bot_token == "123:abc"
    assert s.telegram_chat_id == -1001234567890


def test_leftover_env_keys_are_ignored(make_settings: Callable[..., Settings]) -> None:
    """Keys of removed features linger in deployed .env files — they must not
    kill startup (the production deploy died on exactly this)."""
    s = make_settings(karma_spotify_refresh_token="stale", some_future_key="x")
    assert not hasattr(s, "karma_spotify_refresh_token")


def test_poll_schedule_parses_valid_times(make_settings: Callable[..., Settings]) -> None:
    s = make_settings(poll_schedule="08:00, 20:30")
    assert s.poll_times() == [(8, 0), (20, 30)]


@pytest.mark.parametrize("bad", ["25:00", "08", "ab:cd", "8:00,"])
def test_poll_schedule_rejects_invalid(make_settings: Callable[..., Settings], bad: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(poll_schedule=bad)


@pytest.mark.asyncio
async def test_bot_entrypoint_requires_telegram(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    """src.main (the Telegram bot) must fail fast and clearly without a token."""
    from src import main as main_mod

    monkeypatch.setattr(main_mod, "get_settings", lambda: make_settings())
    with pytest.raises(SystemExit, match="[Tt]elegram"):
        await main_mod.main()
