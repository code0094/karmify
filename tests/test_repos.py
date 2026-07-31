"""Characterization tests for src/db/repos.py on real in-memory SQLite.

Scope note: prod is PostgreSQL — these tests pin query LOGIC, not PG
specifics. Datetimes are naive on purpose (SQLite drops tzinfo).

Intentionally NOT pinned: get_last_liked_at with a NULL liked_at row.
SQLite orders NULLs last on DESC, PostgreSQL orders them FIRST — on prod
one NULL row makes the function return None instead of the real maximum.
A green SQLite test would lie about that; flagged in the coverage report
instead (portable fix would be func.max, which ignores NULLs).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import repos
from src.db.models import GenreAlias, GenrePlaylist, LikedTrack, SpotifyAccount


def _track(**overrides: object) -> LikedTrack:
    defaults: dict[str, object] = {
        "spotify_track_id": "t1",
        "track_name": "Akephale",
        "artist_name": "ROD",
        "liked_by": "karma",
    }
    defaults.update(overrides)
    return LikedTrack(**defaults)  # type: ignore[arg-type]


def _account(**overrides: object) -> SpotifyAccount:
    defaults: dict[str, object] = {
        "user_label": "karma",
        "spotify_user_id": "sp-user",
        "access_token": "acc",
        "refresh_token": "ref",
        "token_expires_at": datetime(2026, 1, 1, 12, 0),
    }
    defaults.update(overrides)
    return SpotifyAccount(**defaults)  # type: ignore[arg-type]


async def _add(session: AsyncSession, *rows: object) -> None:
    session.add_all(rows)
    await session.commit()


# ---- accounts -------------------------------------------------------------


async def test_get_account_found_and_missing(db_session: AsyncSession) -> None:
    await _add(db_session, _account())

    found = await repos.get_account(db_session, "karma")
    assert found is not None
    assert found.spotify_user_id == "sp-user"

    assert await repos.get_account(db_session, "stress303") is None


async def test_update_tokens_persists(db_session: AsyncSession) -> None:
    account = _account()
    await _add(db_session, account)

    await repos.update_tokens(
        db_session,
        user_label="karma",
        access_token="new-acc",
        refresh_token="new-ref",
        expires_at=datetime(2027, 6, 1, 9, 30),
    )

    await db_session.refresh(account)
    assert account.access_token == "new-acc"
    assert account.refresh_token == "new-ref"
    assert account.token_expires_at == datetime(2027, 6, 1, 9, 30)


async def test_update_tokens_unknown_user_is_silent_noop(db_session: AsyncSession) -> None:
    """Pinned footgun: no error for a nonexistent user_label — callers can't rely on one."""
    account = _account()
    await _add(db_session, account)

    await repos.update_tokens(
        db_session,
        user_label="ghost",
        access_token="x",
        refresh_token="y",
        expires_at=datetime(2027, 1, 1),
    )

    await db_session.refresh(account)
    assert account.access_token == "acc"  # existing account untouched


# ---- liked tracks: insert / exists ---------------------------------------


async def test_track_exists_exact_pair_only(db_session: AsyncSession) -> None:
    await _add(db_session, _track())

    assert await repos.track_exists(db_session, "t1", "karma") is True
    assert await repos.track_exists(db_session, "t1", "stress303") is False
    assert await repos.track_exists(db_session, "t2", "karma") is False


async def test_insert_liked_track_returns_row_with_id(db_session: AsyncSession) -> None:
    track = await repos.insert_liked_track(db_session, _track())
    assert track.id is not None


async def test_insert_duplicate_pair_raises(db_session: AsyncSession) -> None:
    """Plain insert by design (no upsert): duplicate (track, user) violates the constraint."""
    await repos.insert_liked_track(db_session, _track())

    with pytest.raises(IntegrityError):
        await repos.insert_liked_track(db_session, _track())
    await db_session.rollback()

    # same track for the OTHER user is fine
    other = await repos.insert_liked_track(db_session, _track(liked_by="stress303"))
    assert other.id is not None


# ---- assignment -----------------------------------------------------------


async def test_assign_sets_all_fields(db_session: AsyncSession) -> None:
    track = await repos.insert_liked_track(db_session, _track())

    await repos.assign_track_to_playlist(
        db_session, track.id, "pl_hg", "karma", telegram_message_id=555
    )

    await db_session.refresh(track)
    assert track.assigned_playlist_id == "pl_hg"
    assert track.assigned_by == "karma"
    assert track.assigned_at is not None
    assert track.telegram_message_id == 555


async def test_unassign_does_not_null_assigned_at(db_session: AsyncSession) -> None:
    """Pinned footgun: None clears playlist/assigned_by, but assigned_at is
    overwritten with the un-assignment time, not cleared."""
    track = await repos.insert_liked_track(db_session, _track())
    await repos.assign_track_to_playlist(db_session, track.id, "pl_hg", "karma")

    await repos.assign_track_to_playlist(db_session, track.id, None, None)

    await db_session.refresh(track)
    assert track.assigned_playlist_id is None
    assert track.assigned_by is None
    assert track.assigned_at is not None


async def test_reassign_without_message_id_clobbers_it(db_session: AsyncSession) -> None:
    """Pinned footgun: omitting telegram_message_id on re-assign resets it to NULL
    (the default None is always written)."""
    track = await repos.insert_liked_track(db_session, _track())
    await repos.assign_track_to_playlist(
        db_session, track.id, "pl_hg", "karma", telegram_message_id=555
    )

    await repos.assign_track_to_playlist(db_session, track.id, "pl_acid", "stress303")

    await db_session.refresh(track)
    assert track.assigned_playlist_id == "pl_acid"
    assert track.telegram_message_id is None


# ---- listing --------------------------------------------------------------


async def test_list_tracks_newest_first_with_limit(db_session: AsyncSession) -> None:
    await _add(
        db_session,
        _track(spotify_track_id="old", created_at=datetime(2026, 7, 1, 10, 0)),
        _track(spotify_track_id="newest", created_at=datetime(2026, 7, 3, 10, 0)),
        _track(spotify_track_id="mid", created_at=datetime(2026, 7, 2, 10, 0)),
    )

    tracks = await repos.list_tracks(db_session, limit=2)

    assert [t.spotify_track_id for t in tracks] == ["newest", "mid"]


async def test_list_tracks_combined_filters(db_session: AsyncSession) -> None:
    await _add(
        db_session,
        _track(spotify_track_id="hit", detected_genre="acid", liked_by="karma"),
        _track(spotify_track_id="wrong-genre", detected_genre="jungle", liked_by="karma"),
        _track(spotify_track_id="wrong-user", detected_genre="acid", liked_by="stress303"),
        _track(
            spotify_track_id="downloaded",
            detected_genre="acid",
            liked_by="karma",
            downloaded_at=datetime(2026, 7, 1),
        ),
    )

    tracks = await repos.list_tracks(
        db_session, genre="acid", liked_by="karma", only_undownloaded=True
    )

    assert [t.spotify_track_id for t in tracks] == ["hit"]


async def test_list_tracks_empty_string_disables_filter(db_session: AsyncSession) -> None:
    """Pinned footgun: genre=""/liked_by="" are falsy — the filter silently no-ops."""
    await _add(
        db_session,
        _track(spotify_track_id="a", detected_genre="acid"),
        _track(spotify_track_id="b", detected_genre="jungle"),
    )

    tracks = await repos.list_tracks(db_session, genre="", liked_by="")

    assert len(tracks) == 2


# ---- playlists and aliases ------------------------------------------------


def _playlist(key: str, name: str) -> GenrePlaylist:
    return GenrePlaylist(genre_key=key, playlist_id=f"pl_{key}", display_name=name)


async def test_get_all_playlists_sorted_by_display_name(db_session: AsyncSession) -> None:
    await _add(
        db_session,
        _playlist("jungle", "jungle"),
        _playlist("acid", "acid"),
        _playlist("hardgroove", "hardgroove"),
    )

    playlists = await repos.get_all_playlists(db_session)

    assert [p.display_name for p in playlists] == ["acid", "hardgroove", "jungle"]


async def test_find_genre_key_normalizes_input(db_session: AsyncSession) -> None:
    await _add(db_session, GenreAlias(alias="techno", genre_key="hardgroove"))

    assert await repos.find_genre_key(db_session, "  Techno ") == "hardgroove"
    assert await repos.find_genre_key(db_session, "polka") is None


async def test_simple_getters(db_session: AsyncSession) -> None:
    playlist = _playlist("acid", "Acid")
    await _add(db_session, playlist)
    track = await repos.insert_liked_track(db_session, _track())

    assert (await repos.get_playlist_by_genre_key(db_session, "acid")) is playlist
    assert (await repos.get_playlist_by_genre_key(db_session, "ghost")) is None
    assert (await repos.get_playlist_by_id(db_session, playlist.id)) is playlist
    assert (await repos.get_playlist_by_id(db_session, 9999)) is None
    assert (await repos.get_track_by_id(db_session, track.id)) is track
    assert (await repos.get_track_by_id(db_session, 9999)) is None


async def test_get_track_for_update_returns_row(db_session: AsyncSession) -> None:
    # SQLite does not render SELECT ... FOR UPDATE — only row retrieval is
    # verified here; the actual lock is a PostgreSQL-only behavior.
    track = await repos.insert_liked_track(db_session, _track())
    assert (await repos.get_track_for_update(db_session, track.id)) is track
    assert (await repos.get_track_for_update(db_session, 9999)) is None


# ---- download state -------------------------------------------------------


async def test_mark_track_downloaded(db_session: AsyncSession) -> None:
    track = await repos.insert_liked_track(db_session, _track())

    await repos.mark_track_downloaded(db_session, track.id, "C:/lib/akephale.mp3")

    await db_session.refresh(track)
    assert track.downloaded_at is not None
    assert track.download_path == "C:/lib/akephale.mp3"

    undownloaded = await repos.list_tracks(db_session, only_undownloaded=True)
    assert undownloaded == []


# ---- last liked timestamp -------------------------------------------------


async def test_get_last_liked_at_empty_is_none(db_session: AsyncSession) -> None:
    assert await repos.get_last_liked_at(db_session, "karma") is None


async def test_get_last_liked_at_max_per_user(db_session: AsyncSession) -> None:
    await _add(
        db_session,
        _track(spotify_track_id="k1", liked_at=datetime(2026, 7, 1, 10, 0)),
        _track(spotify_track_id="k2", liked_at=datetime(2026, 7, 2, 12, 0)),
        _track(
            spotify_track_id="s1",
            liked_by="stress303",
            liked_at=datetime(2026, 7, 5, 15, 0),  # later, must not leak across users
        ),
    )

    assert await repos.get_last_liked_at(db_session, "karma") == datetime(2026, 7, 2, 12, 0)


# ---- download claim (cross-process single-flight) --------------------------


async def test_claim_download_is_exclusive(db_session: AsyncSession) -> None:
    """The second claim loses: the UPDATE is conditional and the DB serializes it."""
    track = await repos.insert_liked_track(db_session, _track())

    assert await repos.claim_download(db_session, track.id, stale_after_sec=600) is True
    assert await repos.claim_download(db_session, track.id, stale_after_sec=600) is False


async def test_release_download_allows_retry(db_session: AsyncSession) -> None:
    track = await repos.insert_liked_track(db_session, _track())
    await repos.claim_download(db_session, track.id, stale_after_sec=600)

    await repos.release_download(db_session, track.id)

    assert await repos.claim_download(db_session, track.id, stale_after_sec=600) is True


async def test_stale_claim_is_taken_over(db_session: AsyncSession) -> None:
    """A process that died mid-download must not block the track forever."""
    track = await repos.insert_liked_track(db_session, _track())
    await repos.claim_download(db_session, track.id, stale_after_sec=600)

    # Same call with a zero-length staleness window: the claim is already old.
    assert await repos.claim_download(db_session, track.id, stale_after_sec=0) is True


async def test_downloaded_track_cannot_be_claimed(db_session: AsyncSession) -> None:
    track = await repos.insert_liked_track(db_session, _track())
    await repos.mark_track_downloaded(db_session, track.id, "a.mp3")

    assert await repos.claim_download(db_session, track.id, stale_after_sec=600) is False


async def test_mark_downloaded_clears_the_claim(db_session: AsyncSession) -> None:
    track = await repos.insert_liked_track(db_session, _track())
    await repos.claim_download(db_session, track.id, stale_after_sec=600)

    await repos.mark_track_downloaded(db_session, track.id, "a.mp3")

    await db_session.refresh(track)
    assert track.download_started_at is None
    assert track.downloaded_at is not None
