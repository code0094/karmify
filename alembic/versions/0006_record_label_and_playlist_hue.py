"""Record label on tracks, colour hue on playlists

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-01

Both feed the redesigned desktop UI: the inbox shows the Discogs label (for
techno it identifies the genre faster than the title does), and every playlist
carries a colour instead of an emoji. The hue is stored rather than derived —
a colour that changed between runs would carry no meaning.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Same order as src/sidecar/context.py PLAYLIST_HUES; the seeded five keep the
#: colours the design assigns them by name.
_SEEDED_HUES = {
    "hardgroove": "#ff6a3d",
    "rave": "#e8c14a",
    "electro": "#4ba3ff",
    "acid": "#3ecf6e",
    "jungle": "#b06aff",
}


def upgrade() -> None:
    op.add_column("liked_tracks", sa.Column("record_label", sa.String(200), nullable=True))
    op.add_column("genre_playlists", sa.Column("hue", sa.String(20), nullable=True))

    playlists = sa.table(
        "genre_playlists", sa.column("genre_key", sa.String), sa.column("hue", sa.String)
    )
    for genre_key, hue in _SEEDED_HUES.items():
        op.execute(playlists.update().where(playlists.c.genre_key == genre_key).values(hue=hue))


def downgrade() -> None:
    op.drop_column("genre_playlists", "hue")
    op.drop_column("liked_tracks", "record_label")
