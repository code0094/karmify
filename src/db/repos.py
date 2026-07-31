"""Repository-pattern database queries."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import GenreAlias, GenrePlaylist, LikedTrack, SpotifyAccount


async def get_account(session: AsyncSession, user_label: str) -> SpotifyAccount | None:
    """Get Spotify account by user label."""
    stmt = select(SpotifyAccount).where(SpotifyAccount.user_label == user_label)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def save_tokens(
    session: AsyncSession,
    user_label: str,
    access_token: str,
    refresh_token: str,
    expires_at: datetime,
) -> None:
    """Store OAuth tokens for a Spotify account, creating the row if needed.

    Nothing else ever inserts into ``spotify_accounts``: a plain UPDATE here
    would silently affect no rows on a fresh database, and every call would go
    back to Spotify's refresh endpoint instead of reusing a stored token.
    """
    stmt = (
        update(SpotifyAccount)
        .where(SpotifyAccount.user_label == user_label)
        .values(
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=expires_at,
        )
    )
    result = await session.execute(stmt)
    if cast("CursorResult[Any]", result).rowcount:
        await session.commit()
        return

    session.add(
        SpotifyAccount(
            user_label=user_label,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=expires_at,
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        # Another process inserted the row first — update it instead.
        await session.rollback()
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
    await session.flush()  # assigns the id; no refresh needed (expire_on_commit=False)
    await session.commit()
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


async def list_tracks(
    session: AsyncSession,
    *,
    genre: str | None = None,
    liked_by: str | None = None,
    only_undownloaded: bool = False,
    limit: int = 200,
) -> list[LikedTrack]:
    """List liked tracks with optional filters, newest first."""
    stmt = select(LikedTrack).order_by(LikedTrack.created_at.desc())
    if genre:
        stmt = stmt.where(LikedTrack.detected_genre == genre)
    if liked_by:
        stmt = stmt.where(LikedTrack.liked_by == liked_by)
    if only_undownloaded:
        stmt = stmt.where(LikedTrack.downloaded_at.is_(None))
    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


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


async def get_playlist_by_genre_key(session: AsyncSession, genre_key: str) -> GenrePlaylist | None:
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
    stmt = select(LikedTrack).where(LikedTrack.id == track_id).with_for_update()
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def claim_download(session: AsyncSession, track_id: int, *, stale_after_sec: int) -> bool:
    """Try to claim a track for downloading; True if this caller won the race.

    One conditional UPDATE, serialized by the database, so the bot and the
    sidecar (separate processes) cannot both start a download for one track.
    A claim older than ``stale_after_sec`` is taken over — otherwise a process
    that died mid-download would block the track forever.
    """
    now = datetime.now().astimezone()
    cutoff = now - timedelta(seconds=stale_after_sec)
    stmt = (
        update(LikedTrack)
        .where(
            LikedTrack.id == track_id,
            LikedTrack.downloaded_at.is_(None),
            (LikedTrack.download_started_at.is_(None)) | (LikedTrack.download_started_at < cutoff),
        )
        .values(download_started_at=now)
    )
    result = await session.execute(stmt)
    await session.commit()
    # UPDATE always yields a CursorResult; Result is just the declared type.
    return bool(cast("CursorResult[Any]", result).rowcount)


async def release_download(session: AsyncSession, track_id: int) -> None:
    """Drop a download claim (failed attempt); the track can be retried."""
    stmt = update(LikedTrack).where(LikedTrack.id == track_id).values(download_started_at=None)
    await session.execute(stmt)
    await session.commit()


async def mark_track_downloaded(session: AsyncSession, track_id: int, download_path: str) -> None:
    """Record that a track's audio has been downloaded to a local path."""
    stmt = (
        update(LikedTrack)
        .where(LikedTrack.id == track_id)
        .values(
            downloaded_at=datetime.now().astimezone(),
            download_path=download_path,
            download_started_at=None,
            last_download_error=None,  # success wipes the stale failure
        )
    )
    await session.execute(stmt)
    await session.commit()


async def set_download_error(session: AsyncSession, track_id: int, error: str) -> None:
    """Record why the last download attempt failed (the UI shows it as ❌)."""
    stmt = update(LikedTrack).where(LikedTrack.id == track_id).values(last_download_error=error)
    await session.execute(stmt)
    await session.commit()


async def list_playlist_tracks(
    session: AsyncSession, playlist_id: str, *, only_undownloaded: bool = False
) -> list[LikedTrack]:
    """Tracks assigned to a Spotify playlist, in insertion order."""
    stmt = (
        select(LikedTrack)
        .where(LikedTrack.assigned_playlist_id == playlist_id)
        .order_by(LikedTrack.id)
    )
    if only_undownloaded:
        stmt = stmt.where(LikedTrack.downloaded_at.is_(None))
    result = await session.execute(stmt)
    return list(result.scalars().all())


@dataclass(frozen=True)
class PlaylistDownloadStats:
    """Per-playlist download progress, derived from track state columns."""

    total: int = 0
    downloaded: int = 0
    downloading: int = 0
    failed: int = 0


async def playlist_download_stats(session: AsyncSession) -> dict[str, PlaylistDownloadStats]:
    """Download progress per Spotify playlist id, one grouped query.

    Status is derived, never stored: downloaded_at → done; a live claim
    (download_started_at) → downloading; an error with no claim → failed, so
    a running retry automatically hides the previous failure.
    """
    downloading = case(
        (
            LikedTrack.download_started_at.is_not(None) & LikedTrack.downloaded_at.is_(None),
            1,
        ),
        else_=0,
    )
    failed = case(
        (
            LikedTrack.last_download_error.is_not(None)
            & LikedTrack.downloaded_at.is_(None)
            & LikedTrack.download_started_at.is_(None),
            1,
        ),
        else_=0,
    )
    stmt = (
        select(
            LikedTrack.assigned_playlist_id,
            func.count(LikedTrack.id),
            func.count(LikedTrack.downloaded_at),  # count(col) skips NULLs
            func.sum(downloading),
            func.sum(failed),
        )
        .where(LikedTrack.assigned_playlist_id.is_not(None))
        .group_by(LikedTrack.assigned_playlist_id)
    )
    result = await session.execute(stmt)
    return {
        playlist_id: PlaylistDownloadStats(
            total=total,
            downloaded=downloaded,
            downloading=int(in_flight or 0),
            failed=int(broken or 0),
        )
        for playlist_id, total, downloaded, in_flight, broken in result.all()
    }


async def get_last_liked_at(session: AsyncSession, user_label: str) -> datetime | None:
    """Get the most recent liked_at timestamp for a user.

    MAX ignores NULLs on every backend; ORDER BY ... DESC LIMIT 1 would return
    a NULL row first on PostgreSQL and report "no likes yet".
    """
    stmt = select(func.max(LikedTrack.liked_at)).where(LikedTrack.liked_by == user_label)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
