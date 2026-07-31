"""The migrations must describe exactly what the models declare.

Without this, a hand-written revision can drift from models.py and every later
`alembic revision --autogenerate` starts with leftover noise nobody intended.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from alembic import command
from src.config import get_settings
from src.db.models import Base

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_REQUIRED_ENV = {
    "SPOTIFY_CLIENT_ID": "x",
    "SPOTIFY_CLIENT_SECRET": "x",
    "KARMA_SPOTIFY_REFRESH_TOKEN": "x",
    "STRESS303_SPOTIFY_REFRESH_TOKEN": "x",
    "DISCOGS_USER_TOKEN": "x",
    "LASTFM_API_KEY": "x",
    "LASTFM_API_SECRET": "x",
}


def test_migrations_produce_the_model_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "migrated.db"
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    get_settings.cache_clear()  # alembic/env.py reads the URL through settings
    monkeypatch.chdir(PROJECT_ROOT)

    try:
        command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    finally:
        get_settings.cache_clear()

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    finally:
        engine.dispose()

    assert diff == [], f"migrations drifted from models.py: {diff}"
