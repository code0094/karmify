"""Application settings loaded from environment variables."""

from pydantic import Field
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

    # Database
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/aux_dj_bot"

    # App
    poll_schedule: str = Field(default="08:00,20:00", description="Comma-separated HH:MM times (UTC)")
    log_level: str = "INFO"

    def poll_times(self) -> list[tuple[int, int]]:
        """Parse poll_schedule into list of (hour, minute) tuples."""
        times: list[tuple[int, int]] = []
        for entry in self.poll_schedule.split(","):
            h, m = entry.strip().split(":")
            times.append((int(h), int(m)))
        return times


def get_settings() -> Settings:
    """Create and return settings instance."""
    return Settings()  # type: ignore[call-arg]
