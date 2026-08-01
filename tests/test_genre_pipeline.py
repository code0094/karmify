"""Tests for the shared resolve-and-store step used by both entrypoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import src.genre.pipeline as pipeline_mod
from src.db import repos
from src.db.models import LikedTrack
from src.genre.pipeline import resolve_and_store_genre
from src.genre.resolver import GenreResult

Factory = async_sessionmaker[AsyncSession]


async def test_resolves_and_persists_genre(
    db_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with db_session_factory() as session:
        track = await repos.insert_liked_track(
            session,
            LikedTrack(
                spotify_track_id="t1", track_name="Akephale", artist_name="ROD", liked_by="karma"
            ),
        )

    resolve = AsyncMock(
        return_value=GenreResult(
            genre_key="hardgroove", raw_genre="hard groove", source="discogs", label="PR"
        )
    )
    monkeypatch.setattr(pipeline_mod, "resolve_genre", resolve)

    result = await resolve_and_store_genre(
        track,
        sp=MagicMock(),
        discogs=MagicMock(),
        lastfm=MagicMock(),
        session_factory=db_session_factory,
    )

    assert result.genre_key == "hardgroove"
    # The waterfall gets the track's own metadata, not the ORM object.
    assert resolve.await_args.kwargs["track_id"] == "t1"
    assert resolve.await_args.kwargs["artist_name"] == "ROD"

    async with db_session_factory() as session:
        stored = await repos.get_track_by_id(session, track.id)
    assert stored is not None
    assert stored.detected_genre == "hardgroove"
    assert stored.genre_source == "discogs"
    # The Discogs label rides along: for techno it identifies the genre faster
    # than anything else on the row, so the library shows it.
    assert stored.record_label == "PR"


async def test_manual_result_is_persisted_too(
    db_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A track nobody could classify must still record source='manual'."""
    async with db_session_factory() as session:
        track = await repos.insert_liked_track(
            session, LikedTrack(spotify_track_id="t2", liked_by="karma")
        )

    monkeypatch.setattr(
        pipeline_mod,
        "resolve_genre",
        AsyncMock(return_value=GenreResult(genre_key=None, raw_genre=None, source="manual")),
    )

    await resolve_and_store_genre(
        track,
        sp=MagicMock(),
        discogs=MagicMock(),
        lastfm=MagicMock(),
        session_factory=db_session_factory,
    )

    async with db_session_factory() as session:
        stored = await repos.get_track_by_id(session, track.id)
    assert stored is not None
    assert stored.detected_genre is None
    assert stored.genre_source == "manual"
