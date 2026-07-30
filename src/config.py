"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration for AUX DJ Bot, loaded from env vars / .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Telegram (optional — required only by the bot entrypoint, src.main;
    # the sidecar runs without it)
    telegram_bot_token: str = ""
    telegram_chat_id: int = 0

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

    # Track downloading (zotify). Audio is fetched on-demand via the ⬇️ button.
    download_dir: str = Field(
        default="downloads", description="Directory where downloaded audio is stored"
    )
    download_format: str = Field(
        default="mp3", description="zotify --codec value (mp3, ogg, opus, copy, ...)"
    )
    download_quality: str = Field(
        default="very_high",
        description="zotify -q value (normal, high, very_high — very_high needs Premium)",
    )
    download_concurrency: int = Field(
        default=1, ge=1, description="Max simultaneous downloads (keep low to avoid bans)"
    )
    download_timeout_sec: int = Field(
        default=300, ge=10, description="Per-download timeout in seconds"
    )
    zotify_credentials_path: str = Field(
        default="",
        description="Path to zotify credentials.json (generated once with a burner account)",
    )
    download_send_to_chat: bool = Field(
        default=True, description="Send the downloaded file into the Telegram chat"
    )
    telegram_upload_limit_mb: int = Field(
        default=50, ge=1, description="Max file size the bot will try to upload to Telegram"
    )

    # Sidecar HTTP API (consumed by the Electron desktop app)
    sidecar_host: str = Field(default="127.0.0.1", description="Sidecar bind host")
    sidecar_port: int = Field(default=8765, ge=1, le=65535, description="Sidecar bind port")
    sidecar_allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        description=(
            "Comma-separated browser origins allowed to call the sidecar. Requests with "
            "no Origin (curl, the Electron main process) are unaffected."
        ),
    )
    sidecar_auth_token: str = Field(
        default="",
        description=(
            "Shared secret required in the X-Aux-Token header. The Electron main process "
            "generates one per run and passes it to both the sidecar and the renderer. "
            "Leave blank only for a trusted local setup: without it the packaged renderer "
            "has to be trusted by its opaque 'null' origin, which any sandboxed iframe "
            "on any website can also present."
        ),
    )

    def allowed_origins(self) -> list[str]:
        """Parse sidecar_allowed_origins into a list (blank entries dropped)."""
        return [o.strip() for o in self.sidecar_allowed_origins.split(",") if o.strip()]

    # Local DJ library (watched folder imported by Rekordbox/Serato)
    library_dir: str = Field(
        default="library", description="Folder where finished tracks are placed for DJ software"
    )

    # Soulseek via slskd daemon (FLAC search/download)
    slskd_url: str = Field(
        default="", description="Base URL of the slskd daemon, e.g. http://127.0.0.1:5030"
    )
    slskd_api_key: str = Field(default="", description="slskd API key")
    slskd_downloads_dir: str = Field(
        default="",
        description="slskd's completed-downloads directory (to collect finished FLACs)",
    )

    # Bandcamp scraper (anonymous name-your-price $0 → email → FLAC)
    bandcamp_mail_imap_host: str = Field(
        default="imap.gmail.com", description="IMAP host of the Bandcamp-link mailbox"
    )
    bandcamp_mail_address: str = Field(default="", description="Mailbox address (use +aliases)")
    bandcamp_mail_password: str = Field(
        default="", description="Mailbox app password (e.g. a Gmail app password)"
    )
    captcha_api_key: str = Field(
        default="", description="CapSolver API key (optional; manual click fallback otherwise)"
    )

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
    return Settings()
