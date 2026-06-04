"""Tests for the local DJ library manager."""

from pathlib import Path

import pytest

from src.library.manager import LibraryManager, _sanitize


def test_sanitize_strips_unsafe() -> None:
    assert _sanitize("dark/techno") == "dark_techno"
    assert _sanitize("a:b|c") == "a_b_c"
    assert _sanitize("") == "misc"


def test_add_copies_into_subdir(tmp_path: Path) -> None:
    src = tmp_path / "track.flac"
    src.write_bytes(b"audio")

    lib = LibraryManager(str(tmp_path / "lib"))
    dest = lib.add(src, subdir="hardgroove")

    assert dest.exists()
    assert dest.read_bytes() == b"audio"
    assert dest.parent.name == "hardgroove"
    # original is preserved (copy, not move)
    assert src.exists()


def test_add_without_subdir(tmp_path: Path) -> None:
    src = tmp_path / "track.mp3"
    src.write_bytes(b"x")
    lib = LibraryManager(str(tmp_path / "lib"))
    dest = lib.add(src)
    assert dest == lib.root / "track.mp3"


def test_add_missing_raises(tmp_path: Path) -> None:
    lib = LibraryManager(str(tmp_path / "lib"))
    with pytest.raises(FileNotFoundError):
        lib.add(tmp_path / "nope.flac")
