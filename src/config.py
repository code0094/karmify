"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration for AUX DJ Bot, loaded from env vars / .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Telegram
    telegram_bot_token: str
    telegram_chat_id: int

    # Spotify (shared app credentials)
    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str = "http://localhost:8888/callback"

    # Spotify per-user refresh tokens
    karma_spotify_refresh_token: str
    stress303_spotify_refresh_token: str

    # Discogs
    discogs_user_token: str

    # Last.fm
    lastfm_api_key: str
    lastfm_api_secret: str

    # Database (no default — must be set explicitly)
    database_url: str

    # App
    poll_schedule: str = Field(
        default="08:00,20:00", description="Comma-separated HH:MM times (UTC)"
    )
    log_level: str = "INFO"

    @field_validator("poll_schedule")
    @classmethod
    def validate_poll_schedule(cls, v: str) -> str:
        """Validate that poll_schedule contains valid HH:MM entries."""
        for entry in v.split(","):
            parts = entry.strip().split(":")
            if len(parts) != 2:
                raise ValueError(f"Invalid time format: {entry!r}, expected HH:MM")
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError(f"Invalid time: {entry!r}, hour must be 0-23, minute 0-59")
        return v

    def poll_times(self) -> list[tuple[int, int]]:
        """Parse poll_schedule into list of (hour, minute) tuples."""
        times: list[tuple[int, int]] = []
        for entry in self.poll_schedule.split(","):
            h, m = entry.strip().split(":")
            times.append((int(h), int(m)))
        return times


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Create and return a cached settings instance."""
    return Settings()  # type: ignore[call-arg]
