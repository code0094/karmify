"""Add liked_tracks.last_download_error for batch playlist downloads

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-31

Playlist downloads run in the background, so failures have nowhere to surface
synchronously — the UI reads them from this column instead. Cleared on a
successful download; a running retry (download_started_at set) hides it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("liked_tracks", sa.Column("last_download_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("liked_tracks", "last_download_error")
