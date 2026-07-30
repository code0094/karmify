"""Tests for Settings: optional credential groups and entrypoint guards."""

from __future__ import annotations

from collections.abc import Callable

import pytest

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


@pytest.mark.asyncio
async def test_bot_entrypoint_requires_telegram(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    """src.main (the Telegram bot) must fail fast and clearly without a token."""
    from src import main as main_mod

    monkeypatch.setattr(main_mod, "get_settings", lambda: make_settings())
    with pytest.raises(SystemExit, match="[Tt]elegram"):
        await main_mod.main()
