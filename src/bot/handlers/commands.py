"""Bot command handlers: /start, /playlists, /stats."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import case, func, select

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
        days = 7
        if message.text:
            parts = message.text.strip().split()
            if len(parts) > 1:
                arg = parts[1]
                if arg == "all":
                    days = 0
                elif arg.isdigit():
                    days = int(arg)

        period_label = f"last {days} days" if days > 0 else "all time"
        since = datetime.now(tz=UTC) - timedelta(days=days) if days > 0 else None

        async with session_factory() as session:
            # Base filter
            base_filter = LikedTrack.created_at >= since if since else True

            # Total count
            total_q = select(func.count()).select_from(LikedTrack).where(base_filter)
            total = (await session.execute(total_q)).scalar() or 0

            if total == 0:
                await message.answer(f"📊 Нет данных за {period_label}")
                return

            # Counts per user
            user_q = (
                select(LikedTrack.liked_by, func.count())
                .where(base_filter)
                .group_by(LikedTrack.liked_by)
            )
            user_rows = (await session.execute(user_q)).all()

            # Auto vs manual count
            auto_q = (
                select(
                    func.count().filter(
                        LikedTrack.genre_source.notin_(["manual", None])
                    ).label("auto"),
                    func.count().filter(
                        LikedTrack.genre_source.in_(["manual", None])
                        | LikedTrack.genre_source.is_(None)
                    ).label("manual"),
                )
                .select_from(LikedTrack)
                .where(base_filter)
            )
            counts = (await session.execute(auto_q)).one()
            auto_count, manual_count = counts.auto, counts.manual

            # Top genres
            genre_q = (
                select(LikedTrack.detected_genre, func.count().label("cnt"))
                .where(base_filter, LikedTrack.detected_genre.isnot(None))
                .group_by(LikedTrack.detected_genre)
                .order_by(func.count().desc())
                .limit(5)
            )
            genre_rows = (await session.execute(genre_q)).all()

        user_parts = " | ".join(f"{u}: {c}" for u, c in sorted(user_rows))
        auto_pct = round(auto_count / total * 100) if total > 0 else 0

        genre_lines = "\n".join(
            f"  {i + 1}. {g} — {c}" for i, (g, c) in enumerate(genre_rows)
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
