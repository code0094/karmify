"""SQLAlchemy ORM models."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """A DJ using Karmify.

    ``label`` is the stable slug the rest of the schema keys on by convention
    (liked_tracks.liked_by, spotify_accounts.user_label) — the schema has no
    FK constraints anywhere, joins are by convention.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(50), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Crew(Base):
    """A group of DJs sharing genre playlists (e.g. AUX MASTERS)."""

    __tablename__ = "crews"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    #: Whose Spotify account hosts the crew's playlists.
    owner_user_id: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CrewMember(Base):
    """Membership: which users are in which crew."""

    __tablename__ = "crew_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_id: Mapped[int] = mapped_column()
    user_id: Mapped[int] = mapped_column()

    __table_args__ = (UniqueConstraint("crew_id", "user_id"),)


class SpotifyAccount(Base):
    """Spotify OAuth tokens for each DJ account."""

    __tablename__ = "spotify_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_label: Mapped[str] = mapped_column(String(50), unique=True)
    #: Not fetched anywhere yet — rows are created on the first token refresh,
    #: when only the tokens themselves are known.
    spotify_user_id: Mapped[str | None] = mapped_column(String(255))
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
    #: Which crew shares this playlist; NULL only before the first bootstrap.
    crew_id: Mapped[int | None] = mapped_column()
    #: Colour identifying the playlist across the UI (replaces the emoji there).
    #: Stored, not derived — a colour that moved between runs would be useless.
    hue: Mapped[str | None] = mapped_column(String(20))


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
    #: Record label from Discogs. For techno it identifies the genre faster than
    #: anything else, so the inbox shows it next to the title.
    record_label: Mapped[str | None] = mapped_column(String(200))
    assigned_playlist_id: Mapped[str | None] = mapped_column(String(255))
    assigned_by: Mapped[str | None] = mapped_column(String(50))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    download_path: Mapped[str | None] = mapped_column(String(1000))
    #: Which source actually delivered the file. A track that fell through to
    #: Spotify's 320 kbps is a candidate for re-pulling in lossless later.
    download_source: Mapped[str | None] = mapped_column(String(20))
    #: Set while a download is in flight — the cross-process single-flight claim
    #: (the bot and the sidecar are separate processes on one database).
    download_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Why the last download attempt failed; cleared on success. Download status
    #: is derived, not stored: downloaded_at → done, download_started_at →
    #: running, this field alone → failed (a retry's claim hides the old error).
    last_download_error: Mapped[str | None] = mapped_column(Text)
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
