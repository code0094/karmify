"""Seed the default crew on startup.

The database is the source of truth for who uses Karmify — settings provide
only the very first composition (``DEFAULT_USERS`` / ``DEFAULT_CREW_NAME``).
After the first run, adding a member is an INSERT, not a code or config change,
and re-running never removes anyone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from src.db import repos

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.config import Settings
    from src.db.models import Crew, User

logger = structlog.get_logger()


async def ensure_default_crew(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> tuple[Crew | None, list[User]]:
    """Idempotently seed users + crew + membership; returns (crew, all users).

    The first default label owns the crew — its Spotify account is where the
    crew's playlists live. Playlists created before crews existed are adopted.
    """
    async with session_factory() as session:
        defaults = [
            await repos.ensure_user(session, label=label)
            for label in settings.default_user_labels()
        ]
        crew = await repos.get_crew(session)
        if crew is None and defaults:
            crew = await repos.ensure_crew(
                session, name=settings.default_crew_name, owner_user_id=defaults[0].id
            )
            logger.info("bootstrap.crew_created", crew=crew.name, owner=defaults[0].label)
        if crew is not None:
            for user in defaults:
                await repos.ensure_crew_member(session, crew_id=crew.id, user_id=user.id)
            adopted = await repos.adopt_orphan_playlists(session, crew.id)
            if adopted:
                logger.info("bootstrap.playlists_adopted", crew=crew.name, count=adopted)
        users = await repos.list_users(session)
    return crew, users
