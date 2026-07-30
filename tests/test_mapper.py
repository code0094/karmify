"""Tests for genre mapper."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.genre.mapper import map_to_genre_key


@pytest.mark.asyncio
async def test_map_finds_matching_genre() -> None:
    """Mapper returns genre_key when alias matches."""
    session = AsyncMock()
    session.execute = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = "hardgroove"
    session.execute.return_value = mock_result

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await map_to_genre_key(factory, ["dark techno", "industrial"])
    assert result == "hardgroove"


@pytest.mark.asyncio
async def test_map_returns_none_when_no_match() -> None:
    """Mapper returns None when no alias matches."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await map_to_genre_key(factory, ["unknown genre", "random tag"])
    assert result is None


@pytest.mark.asyncio
async def test_map_first_matching_raw_wins_and_stops() -> None:
    """Priority: raws are tried in order and the search stops on the first hit."""
    session = AsyncMock()
    miss = MagicMock()
    miss.scalar_one_or_none.return_value = None
    hit = MagicMock()
    hit.scalar_one_or_none.return_value = "jungle"
    session.execute = AsyncMock(side_effect=[miss, hit])

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)

    result = await map_to_genre_key(factory, ["nomatch", "ragga jungle", "electro"])

    assert result == "jungle"
    assert session.execute.call_count == 2  # stopped at the match, third raw untouched
