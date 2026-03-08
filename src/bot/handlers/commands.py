"""Bot command handlers: /start, /playlists, /stats."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select

from src.db.models import LikedTrack

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

router = Router()


def setup_command_router(session_factory: async_sessionmaker[AsyncSession]) -> Router:
    """Create and return a router with command handlers."""

    @router.message(Command("start"))
    async def handle_start(message: Message) -> None:
        await message.answer(
            "🎵 AUX DJ Bot\n"
            "Мониторю лайки в Spotify и помогаю сортировать по жанровым плейлистам.\n\n"
            "Команды:\n"
            "/playlists — список плейлистов\n"
            "/stats — статистика за неделю\n"
            "/stats 30 — статистика за 30 дней"
        )

    @router.message(Command("playlists"))
    async def handle_playlists(message: Message) -> None:
        from src.db import repos

        async with session_factory() as session:
            playlists = await repos.get_all_playlists(session)

        if not playlists:
            await message.answer("Плейлисты не настроены.")
            return

        lines = ["📋 Жанровые плейлисты:"]
        for pl in playlists:
            lines.append(f"  {pl.emoji} {pl.display_name} — `{pl.genre_key}`")

        await message.answer("\n".join(lines), parse_mode="Markdown")

    @router.message(Command("stats"))
    async def handle_stats(message: Message) -> None:
        # Parse period from args
        days = 7
        if message.text:
            parts = message.text.strip().split()
            if len(parts) > 1:
                arg = parts[1]
                if arg == "all":
                    days = 0
                elif arg.isdigit():
                    days = int(arg)

        async with session_factory() as session:
            query = select(LikedTrack)
            if days > 0:
                since = datetime.now(tz=UTC) - timedelta(days=days)
                query = query.where(LikedTrack.created_at >= since)

            result = await session.execute(query)
            tracks = list(result.scalars().all())

        total = len(tracks)
        if total == 0:
            period_label = f"last {days} days" if days > 0 else "all time"
            await message.answer(f"📊 Нет данных за {period_label}")
            return

        # Count per user
        by_user: dict[str, int] = {}
        auto_count = 0
        manual_count = 0
        genre_counts: dict[str, int] = {}

        for t in tracks:
            by_user[t.liked_by] = by_user.get(t.liked_by, 0) + 1
            if t.genre_source and t.genre_source != "manual":
                auto_count += 1
            else:
                manual_count += 1
            if t.detected_genre:
                genre_counts[t.detected_genre] = genre_counts.get(t.detected_genre, 0) + 1

        # Format
        period_label = f"last {days} days" if days > 0 else "all time"
        user_parts = " | ".join(f"{u}: {c}" for u, c in sorted(by_user.items()))
        auto_pct = round(auto_count / total * 100) if total > 0 else 0

        top_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        genre_lines = "\n".join(
            f"  {i+1}. {g} — {c}" for i, (g, c) in enumerate(top_genres)
        )

        text = (
            f"📊 Статистика AUX MASTERS ({period_label}):\n"
            f"├ Всего лайков: {total}\n"
            f"├ {user_parts}\n"
            f"├ Автоматически определено: {auto_count} ({auto_pct}%)\n"
            f"├ Вручную: {manual_count}\n"
            f"└ Топ жанры:\n{genre_lines}"
        )

        await message.answer(text)

    return router
