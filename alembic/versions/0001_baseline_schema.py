"""Baseline schema (the tables that existed before migrations were introduced)

Revision ID: 0001
Revises:
Create Date: 2026-07-31

On a database that already has these tables (the VPS, created by hand), run
``alembic stamp 0001`` instead of upgrading — that records the baseline as
applied without touching the data. New databases get it via ``alembic upgrade
head`` as usual.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "spotify_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_label", sa.String(50), nullable=False, unique=True),
        sa.Column("spotify_user_id", sa.String(255), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "genre_playlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("genre_key", sa.String(100), nullable=False, unique=True),
        sa.Column("playlist_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("emoji", sa.String(10), nullable=False),
    )
    op.create_table(
        "liked_tracks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("spotify_track_id", sa.String(255), nullable=False),
        sa.Column("track_name", sa.String(500)),
        sa.Column("artist_name", sa.String(500)),
        sa.Column("liked_by", sa.String(50), nullable=False),
        sa.Column("liked_at", sa.DateTime(timezone=True)),
        sa.Column("detected_genre", sa.String(100)),
        sa.Column("genre_source", sa.String(20)),
        sa.Column("assigned_playlist_id", sa.String(255)),
        sa.Column("assigned_by", sa.String(50)),
        sa.Column("assigned_at", sa.DateTime(timezone=True)),
        sa.Column("telegram_message_id", sa.BigInteger()),
        sa.Column("downloaded_at", sa.DateTime(timezone=True)),
        sa.Column("download_path", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("spotify_track_id", "liked_by"),
    )
    op.create_table(
        "genre_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alias", sa.String(200), nullable=False, unique=True),
        sa.Column("genre_key", sa.String(100), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("genre_aliases")
    op.drop_table("liked_tracks")
    op.drop_table("genre_playlists")
    op.drop_table("spotify_accounts")
