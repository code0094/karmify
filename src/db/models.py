"""SQLAlchemy ORM models."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SpotifyAccount(Base):
    """Spotify OAuth tokens for each DJ account."""

    __tablename__ = "spotify_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_label: Mapped[str] = mapped_column(String(50), unique=True)
    spotify_user_id: Mapped[str] = mapped_column(String(255))
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class GenrePlaylist(Base):
    """Genre-to-Spotify-playlist mapping."""

    __tablename__ = "genre_playlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    genre_key: Mapped[str] = mapped_column(String(100), unique=True)
    playlist_id: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    emoji: Mapped[str] = mapped_column(String(10), default="🎵")


class LikedTrack(Base):
    """Every processed liked track."""

    __tablename__ = "liked_tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    spotify_track_id: Mapped[str] = mapped_column(String(255))
    track_name: Mapped[str | None] = mapped_column(String(500))
    artist_name: Mapped[str | None] = mapped_column(String(500))
    liked_by: Mapped[str] = mapped_column(String(50))
    liked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detected_genre: Mapped[str | None] = mapped_column(String(100))
    genre_source: Mapped[str | None] = mapped_column(String(20))
    assigned_playlist_id: Mapped[str | None] = mapped_column(String(255))
    assigned_by: Mapped[str | None] = mapped_column(String(50))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("spotify_track_id", "liked_by"),)


class GenreAlias(Base):
    """Alias table for fuzzy genre → genre_key mapping."""

    __tablename__ = "genre_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(200), unique=True)
    genre_key: Mapped[str] = mapped_column(String(100))
