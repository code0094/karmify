"""Tests for bot command handlers: /stats on real SQLite, /fetch on mocks.

Handlers are registered on the MODULE-level router in commands.py, so every
setup_command_router() call in tests stacks another copy; helpers below always
take the LAST registered handler by function name. (The module-level router is
itself flagged in the coverage report — in prod it is only called once.)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import src.bot.handlers.commands as commands_mod
from src.bot.handlers.commands import setup_command_router
from src.db.models import LikedTrack

Factory = async_sessionmaker[AsyncSession]


def _get_handler(name: str) -> Callable[..., Awaitable[None]]:
    handlers = [
        h.callback for h in commands_mod.router.message.handlers if h.callback.__name__ == name
    ]
    assert handlers, f"handler {name} not registered"
    return handlers[-1]


def _message(text: str) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.answer = AsyncMock()
    return msg


def _track(track_id: str, **overrides: object) -> LikedTrack:
    defaults: dict[str, object] = {
        "spotify_track_id": track_id,
        "track_name": f"Track {track_id}",
        "artist_name": "ROD",
        "liked_by": "karma",
    }
    defaults.update(overrides)
    return LikedTrack(**defaults)


async def _seed(factory: Factory, *tracks: LikedTrack) -> None:
    async with factory() as session:
        session.add_all(tracks)
        await session.commit()


def _stats_seed() -> list[LikedTrack]:
    return [
        _track("k1", genre_source="spotify", detected_genre="hardgroove"),
        _track("s1", liked_by="stress303", genre_source="spotify", detected_genre="hardgroove"),
        _track("k2", genre_source="manual", detected_genre="acid"),
    ]


# ---- /stats ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("/stats", "last 7 days"),
        ("/stats 30", "last 30 days"),
        ("/stats all", "all time"),
        ("/stats мусор", "last 7 days"),
    ],
)
async def test_stats_period_parsing_on_empty_db(
    db_session_factory: Factory, text: str, label: str
) -> None:
    setup_command_router(db_session_factory, AsyncMock())
    handler = _get_handler("handle_stats")
    msg = _message(text)

    await handler(msg)

    msg.answer.assert_awaited_once()
    answer = msg.answer.await_args.args[0]
    assert "Нет данных" in answer
    assert label in answer


async def test_stats_counts_users_manual_and_genre_order(db_session_factory: Factory) -> None:
    await _seed(db_session_factory, *_stats_seed())
    setup_command_router(db_session_factory, AsyncMock())
    msg = _message("/stats")

    await _get_handler("handle_stats")(msg)

    answer = msg.answer.await_args.args[0]
    assert "Всего лайков: 3" in answer
    assert "karma: 2 | stress303: 1" in answer
    assert "Вручную: 1" in answer
    # hardgroove (2 tracks) must rank above acid (1 track)
    assert answer.index("hardgroove") < answer.index("acid")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="known bug: notin_(['manual', None]) renders NOT IN ('manual', NULL) "
    "which never matches — the auto counter is always 0",
)
async def test_stats_auto_count_desired_behavior(db_session_factory: Factory) -> None:
    await _seed(db_session_factory, *_stats_seed())
    setup_command_router(db_session_factory, AsyncMock())
    msg = _message("/stats")

    await _get_handler("handle_stats")(msg)

    # Desired: two spotify-resolved tracks count as automatically detected.
    assert "Автоматически определено: 2" in msg.answer.await_args.args[0]


async def test_stats_period_filter_on_created_at(db_session_factory: Factory) -> None:
    now = datetime.now()
    await _seed(
        db_session_factory,
        _track("old", created_at=now - timedelta(days=40)),
        _track("new", created_at=now - timedelta(days=1)),
    )
    setup_command_router(db_session_factory, AsyncMock())
    handler = _get_handler("handle_stats")

    msg_30 = _message("/stats 30")
    await handler(msg_30)
    assert "Всего лайков: 1" in msg_30.answer.await_args.args[0]

    msg_all = _message("/stats all")
    await handler(msg_all)
    assert "Всего лайков: 2" in msg_all.answer.await_args.args[0]


# ---- /fetch ----------------------------------------------------------------


def _fetch_handler(fetch_likes: AsyncMock) -> Callable[..., Awaitable[None]]:
    setup_command_router(MagicMock(), fetch_likes)
    return _get_handler("handle_fetch")


async def test_fetch_reports_new_tracks() -> None:
    msg = _message("/fetch")

    await _fetch_handler(AsyncMock(return_value=3))(msg)

    assert msg.answer.await_count == 2  # "checking…" preamble + result
    assert "Найдено новых треков: 3" in msg.answer.await_args.args[0]


async def test_fetch_reports_nothing_new() -> None:
    msg = _message("/fetch")

    await _fetch_handler(AsyncMock(return_value=0))(msg)

    assert "Новых лайков нет" in msg.answer.await_args.args[0]


async def test_fetch_error_is_reported_not_raised() -> None:
    msg = _message("/fetch")

    await _fetch_handler(AsyncMock(side_effect=RuntimeError("spotify down")))(msg)

    assert "Ошибка" in msg.answer.await_args.args[0]
