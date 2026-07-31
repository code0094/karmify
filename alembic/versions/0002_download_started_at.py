"""Add liked_tracks.download_started_at for a cross-process download claim

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-31

The bot and the sidecar are separate processes sharing one database, so an
in-memory guard cannot stop both from downloading the same track. This column
is claimed with a conditional UPDATE, which the database serializes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "liked_tracks",
        sa.Column("download_started_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("liked_tracks", "download_started_at")
