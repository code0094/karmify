"""Tests for genre resolver waterfall.

Two kinds of tests here: the original two are end-to-end smokes through real
lookup+mapper code on mocked API clients; the routing tests below patch the
lookup functions and the mapper to pin ONLY the cascade routing itself.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import src.genre.resolver as resolver_mod
from src.genre.resolver import resolve_genre


@pytest.mark.asyncio
async def test_resolve_from_spotify(
    mock_spotify: MagicMock,
    mock_discogs: MagicMock,
    mock_lastfm: MagicMock,
) -> None:
    """Resolver finds genre from Spotify artist genres (level 1)."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = "hardgroove"
    session.execute.return_value = mock_result

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await resolve_genre(
        track_id="track123",
        artist_name="ROD",
        track_name="Akephale",
        sp=mock_spotify,
        discogs=mock_discogs,
        lastfm=mock_lastfm,
        session_factory=factory,
    )

    assert result.has_match()
    assert result.genre_key == "hardgroove"
    assert result.source == "spotify"


@pytest.mark.asyncio
async def test_resolve_falls_through_to_manual(
    mock_spotify: MagicMock,
    mock_discogs: MagicMock,
    mock_lastfm: MagicMock,
) -> None:
    """Resolver returns manual when all levels fail to match."""
    # Make Spotify return no genres
    mock_spotify.artists.return_value = {"artists": [{"id": "a1", "genres": []}]}

    # Make Discogs return nothing
    empty_results = MagicMock()
    empty_results.count = 0
    empty_results.__getitem__ = MagicMock(side_effect=IndexError)
    mock_discogs.search.return_value = empty_results

    # Make Last.fm return nothing
    mock_lastfm.get_track.return_value.get_top_tags.return_value = []

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await resolve_genre(
        track_id="track_unknown",
        artist_name="Unknown Artist",
        track_name="Unknown Track",
        sp=mock_spotify,
        discogs=mock_discogs,
        lastfm=mock_lastfm,
        session_factory=factory,
    )

    assert not result.has_match()
    assert result.source == "manual"


# ---- cascade routing (lookups and mapper patched) -------------------------


def _patch_cascade(
    monkeypatch: pytest.MonkeyPatch,
    *,
    spotify: list[str] | None = None,
    discogs: list[str] | None = None,
    lastfm: list[str] | None = None,
    mapper: AsyncMock,
    label: str | None = "Planet Rhythm",
) -> AsyncMock:
    """Patch all cascade inputs; returns the get_label mock."""
    monkeypatch.setattr(
        resolver_mod.spotify_genres,
        "get_artist_genres",
        AsyncMock(return_value=spotify or []),
    )
    monkeypatch.setattr(
        resolver_mod.discogs_lookup, "search_genre", AsyncMock(return_value=discogs or [])
    )
    monkeypatch.setattr(
        resolver_mod.lastfm_tags, "get_top_tags", AsyncMock(return_value=lastfm or [])
    )
    label_mock = AsyncMock(return_value=label)
    monkeypatch.setattr(resolver_mod.discogs_lookup, "get_label", label_mock)
    # NB: resolver imports map_to_genre_key by name — patch ITS namespace,
    # not src.genre.mapper (a from-import would never see that patch).
    monkeypatch.setattr(resolver_mod, "map_to_genre_key", mapper)
    return label_mock


async def _resolve() -> "resolver_mod.GenreResult":
    return await resolve_genre(
        track_id="t1",
        artist_name="ROD",
        track_name="Akephale",
        sp=MagicMock(),
        discogs=MagicMock(),
        lastfm=MagicMock(),
        session_factory=MagicMock(),
    )


@pytest.mark.asyncio
async def test_level2_discogs_wins_when_spotify_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cascade(
        monkeypatch,
        discogs=["Hardgroove"],
        mapper=AsyncMock(return_value="hardgroove"),
    )

    result = await _resolve()

    assert result.source == "discogs"
    assert result.genre_key == "hardgroove"
    assert result.label == "Planet Rhythm"


@pytest.mark.asyncio
async def test_level3_lastfm_wins_when_discogs_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cascade(monkeypatch, lastfm=["techno"], mapper=AsyncMock(return_value="hardgroove"))

    result = await _resolve()

    assert result.source == "lastfm"


@pytest.mark.asyncio
async def test_raw_genre_is_first_item_not_the_matched_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pinned quirk: raw_genre records raw_genres[0], not the alias that matched
    (the mapper does not report which raw won) — see coverage report flag."""
    _patch_cascade(
        monkeypatch,
        discogs=["Electronic", "Hardgroove"],
        mapper=AsyncMock(return_value="hardgroove"),
    )

    result = await _resolve()

    assert result.raw_genre == "Electronic"


@pytest.mark.asyncio
async def test_raw_without_alias_falls_through_to_next_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A level that returns raw genres but maps to no alias must NOT win."""
    mapper = AsyncMock(side_effect=[None, "hardgroove"])
    _patch_cascade(monkeypatch, spotify=["obscure"], discogs=["Hardgroove"], mapper=mapper)

    result = await _resolve()

    assert result.source == "discogs"
    assert mapper.await_count == 2


@pytest.mark.asyncio
async def test_manual_still_carries_label_and_fetches_it_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All levels return raws, none map: manual result still carries the label
    (fetched exactly once, before the cascade)."""
    label_mock = _patch_cascade(
        monkeypatch,
        spotify=["a"],
        discogs=["b"],
        lastfm=["c"],
        mapper=AsyncMock(return_value=None),
    )

    result = await _resolve()

    assert result.source == "manual"
    assert result.genre_key is None
    assert result.label == "Planet Rhythm"
    assert label_mock.await_count == 1


@pytest.mark.asyncio
async def test_level1_spotify_wins_over_lower_levels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cascade(
        monkeypatch,
        spotify=["hard groove"],
        discogs=["X"],
        lastfm=["Y"],
        mapper=AsyncMock(return_value="hardgroove"),
    )

    result = await _resolve()

    assert result.source == "spotify"
    assert result.genre_key == "hardgroove"
