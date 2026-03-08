"""Repository-pattern database queries."""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import GenreAlias, GenrePlaylist, LikedTrack, SpotifyAccount


async def get_account(session: AsyncSession, user_label: str) -> SpotifyAccount | None:
    """Get Spotify account by user label."""
    stmt = select(SpotifyAccount).where(SpotifyAccount.user_label == user_label)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_tokens(
    session: AsyncSession,
    user_label: str,
    access_token: str,
    refresh_token: str,
    expires_at: datetime,
) -> None:
    """Update OAuth tokens for a Spotify account."""
    stmt = (
        update(SpotifyAccount)
        .where(SpotifyAccount.user_label == user_label)
        .values(
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=expires_at,
        )
    )
    await session.execute(stmt)
    await session.commit()


async def track_exists(session: AsyncSession, spotify_track_id: str, liked_by: str) -> bool:
    """Check if a liked track is already in DB."""
    stmt = select(LikedTrack.id).where(
        LikedTrack.spotify_track_id == spotify_track_id,
        LikedTrack.liked_by == liked_by,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def insert_liked_track(session: AsyncSession, track: LikedTrack) -> LikedTrack:
    """Insert a new liked track. Returns the inserted row with a valid DB id."""
    session.add(track)
    await session.flush()
    await session.commit()
    await session.refresh(track)
    return track


async def assign_track_to_playlist(
    session: AsyncSession,
    track_id: int,
    playlist_id: str | None,
    assigned_by: str | None,
    telegram_message_id: int | None = None,
) -> None:
    """Assign a liked track to a playlist."""
    stmt = (
        update(LikedTrack)
        .where(LikedTrack.id == track_id)
        .values(
            assigned_playlist_id=playlist_id,
            assigned_by=assigned_by,
            assigned_at=datetime.now().astimezone(),
            telegram_message_id=telegram_message_id,
        )
    )
    await session.execute(stmt)
    await session.commit()


async def get_all_playlists(session: AsyncSession) -> list[GenrePlaylist]:
    """Get all genre playlists."""
    stmt = select(GenrePlaylist).order_by(GenrePlaylist.display_name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def find_genre_key(session: AsyncSession, genre_string: str) -> str | None:
    """Look up genre_key by alias (normalized)."""
    normalized = genre_string.lower().strip()
    stmt = select(GenreAlias.genre_key).where(GenreAlias.alias == normalized)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_playlist_by_genre_key(
    session: AsyncSession, genre_key: str
) -> GenrePlaylist | None:
    """Get playlist for a genre key."""
    stmt = select(GenrePlaylist).where(GenrePlaylist.genre_key == genre_key)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_playlist_by_id(session: AsyncSession, playlist_id: int) -> GenrePlaylist | None:
    """Get genre playlist by primary key."""
    return await session.get(GenrePlaylist, playlist_id)


async def get_track_by_id(session: AsyncSession, track_id: int) -> LikedTrack | None:
    """Get liked track by primary key."""
    return await session.get(LikedTrack, track_id)


async def get_track_for_update(session: AsyncSession, track_id: int) -> LikedTrack | None:
    """Get liked track with row-level lock (SELECT FOR UPDATE)."""
    stmt = (
        select(LikedTrack)
        .where(LikedTrack.id == track_id)
        .with_for_update()
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_last_liked_at(session: AsyncSession, user_label: str) -> datetime | None:
    """Get the most recent liked_at timestamp for a user."""
    stmt = (
        select(LikedTrack.liked_at)
        .where(LikedTrack.liked_by == user_label)
        .order_by(LikedTrack.liked_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
