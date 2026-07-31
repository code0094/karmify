"""Tests for the startup crew seeding (src/db/bootstrap.py).

The database is the source of truth for who uses Karmify; settings provide
only the very first composition. Everything runs on real in-memory SQLite.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import Settings
from src.db import repos
from src.db.bootstrap import ensure_default_crew


async def test_first_run_seeds_users_crew_and_membership(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    crew, users = await ensure_default_crew(db_session_factory, make_settings())

    assert crew is not None
    assert crew.name == "AUX MASTERS"
    assert [u.label for u in users] == ["karma", "stress303"]
    assert crew.owner_user_id == users[0].id  # first default label owns the crew

    async with db_session_factory() as session:
        members = await repos.get_crew_members(session, crew.id)
        assert [m.label for m in members] == ["karma", "stress303"]


async def test_rerun_is_idempotent_and_keeps_added_members(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """New members are added as rows, not settings — a re-run must keep them."""
    settings = make_settings()
    crew, _ = await ensure_default_crew(db_session_factory, settings)
    assert crew is not None
    async with db_session_factory() as session:
        egor = await repos.ensure_user(session, label="egor", display_name="Егор")
        await repos.ensure_crew_member(session, crew_id=crew.id, user_id=egor.id)

    crew_again, users = await ensure_default_crew(db_session_factory, settings)

    assert crew_again is not None and crew_again.id == crew.id
    assert [u.label for u in users] == ["karma", "stress303", "egor"]
    async with db_session_factory() as session:
        assert len(await repos.list_users(session)) == 3


async def test_orphan_playlists_are_adopted_by_the_crew(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await repos.add_genre_playlist(
            session, genre_key="acid", playlist_id="pl_a", display_name="Acid", emoji="🧪"
        )

    crew, _ = await ensure_default_crew(db_session_factory, make_settings())

    assert crew is not None
    async with db_session_factory() as session:
        playlist = await repos.get_playlist_by_genre_key(session, "acid")
        assert playlist is not None and playlist.crew_id == crew.id


async def test_no_default_users_means_no_crew(
    make_settings: Callable[..., Settings],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    crew, users = await ensure_default_crew(db_session_factory, make_settings(default_users=""))

    assert crew is None
    assert users == []
