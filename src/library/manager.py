"""Library manager: place finished tracks into a watched folder.

Rekordbox and Serato import from folders on disk, so the simplest reliable
integration is to copy finished downloads into a library directory (optionally
organised into sub-folders, e.g. by genre) that the DJ software watches/imports.

We copy rather than move so the source download cache stays intact for dedup.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import structlog

logger = structlog.get_logger()

_UNSAFE = re.compile(r'[<>:"/\\|?*]')


def _sanitize(name: str) -> str:
    """Strip filesystem-unsafe characters from a sub-folder name."""
    return _UNSAFE.sub("_", name).strip().strip(".") or "misc"


class LibraryManager:
    """Copies finished track files into the local DJ library folder."""

    def __init__(self, library_dir: str) -> None:
        self._dir = Path(library_dir)

    @property
    def root(self) -> Path:
        return self._dir

    def add(self, src: Path, *, subdir: str | None = None) -> Path:
        """Copy ``src`` into the library (optionally under ``subdir``) and return its path.

        Args:
            src: Path to the downloaded audio file.
            subdir: Optional sub-folder (e.g. genre); sanitized for the filesystem.

        Returns:
            The destination path inside the library.

        Raises:
            FileNotFoundError: If ``src`` does not exist.
        """
        if not src.is_file():
            raise FileNotFoundError(f"Source file not found: {src}")

        target_dir = self._dir / _sanitize(subdir) if subdir else self._dir
        target_dir.mkdir(parents=True, exist_ok=True)

        dest = target_dir / src.name
        if dest.exists() and dest.resolve() == src.resolve():
            return dest
        if dest.exists():
            dest.unlink()

        shutil.copy2(src, dest)
        logger.info("library.added", file=src.name, path=str(dest))
        return dest
