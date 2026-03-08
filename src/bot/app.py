"""Aiogram Dispatcher setup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher

from src.bot.handlers.callbacks import setup_callback_router
from src.bot.handlers.commands import setup_command_router
from src.bot.handlers.errors import router as error_router

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.spotify.client import SpotifyClient


def create_dispatcher(
    session_factory: async_sessionmaker[AsyncSession],
    spotify_clients: dict[str, SpotifyClient],
) -> Dispatcher:
    """Build and configure the aiogram Dispatcher with all routers."""
    dp = Dispatcher()

    dp.include_router(error_router)
    dp.include_router(setup_command_router(session_factory))
    dp.include_router(setup_callback_router(session_factory, spotify_clients))

    return dp


def create_bot(token: str) -> Bot:
    """Create the aiogram Bot instance."""
    return Bot(token=token)
