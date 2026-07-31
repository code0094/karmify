"""Users and crews: who uses Karmify and who shares playlists with whom

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-31

Replaces the karma/stress303 hardcode: accounts become rows in ``users``,
groups sharing genre playlists become ``crews`` with ``crew_members``.
Pure schema — the default crew is seeded at startup (src/db/bootstrap.py),
so a fresh install is not baked to any particular pair of DJs.

Like the rest of this schema, joins are by convention (no FK constraints);
``liked_tracks.liked_by`` keeps referencing ``users.label``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(50), nullable=False, unique=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "crews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "crew_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("crew_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.UniqueConstraint("crew_id", "user_id"),
    )
    op.add_column("genre_playlists", sa.Column("crew_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("genre_playlists", "crew_id")
    op.drop_table("crew_members")
    op.drop_table("crews")
    op.drop_table("users")
