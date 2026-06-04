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
