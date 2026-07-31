"""Allow spotify_accounts.spotify_user_id to be NULL

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-31

Token rows are created on the first refresh, when only the tokens are known —
the Spotify user id is not fetched anywhere in the app (nothing reads it).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("spotify_accounts") as batch:
        batch.alter_column("spotify_user_id", existing_type=sa.String(255), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("spotify_accounts") as batch:
        batch.alter_column("spotify_user_id", existing_type=sa.String(255), nullable=False)
