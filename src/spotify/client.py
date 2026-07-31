"""Spotipy wrapper with DB-backed token refresh for multiple accounts."""

import asyncio
from datetime import UTC, datetime, timedelta

import spotipy
import structlog
from spotipy.oauth2 import SpotifyOAuth
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import Settings
from src.db import repos

logger = structlog.get_logger()


class NotAuthorizedError(Exception):
    """Raised when an account has no stored tokens and no fallback token."""


SCOPES = "user-library-read playlist-modify-public playlist-modify-private"


def _as_aware(value: datetime) -> datetime:
    """PostgreSQL returns aware datetimes; a naive one must not raise here."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class SpotifyClient:
    """Manages a Spotify API client for one user account with DB-backed token refresh."""

    def __init__(
        self,
        user_label: str,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.user_label = user_label
        self._session_factory = session_factory
        self._oauth = SpotifyOAuth(
            client_id=settings.spotify_client_id,
            client_secret=settings.spotify_client_secret,
            redirect_uri=settings.spotify_redirect_uri,
            scope=SCOPES,
        )

    async def _refresh_and_store(self, refresh_token: str) -> str:
        """Refresh access token via Spotify and store new tokens in DB."""
        token_info = await asyncio.to_thread(self._oauth.refresh_access_token, refresh_token)
        access_token: str = token_info["access_token"]
        new_refresh: str = token_info.get("refresh_token", refresh_token)
        expires_at = datetime.now(tz=UTC) + timedelta(seconds=token_info["expires_in"])

        async with self._session_factory() as session:
            await repos.save_tokens(
                session,
                user_label=self.user_label,
                access_token=access_token,
                refresh_token=new_refresh,
                expires_at=expires_at,
            )

        logger.info("spotify.token_refreshed", user=self.user_label)
        return access_token

    async def get_client(self) -> spotipy.Spotify:
        """Return a ready-to-use Spotify client, refreshing token if needed.

        The database is the only token store — no row means the user never
        completed "Log in with Spotify" in the app.
        """
        async with self._session_factory() as session:
            account = await repos.get_account(session, self.user_label)

        if account is None:
            raise NotAuthorizedError(
                f"Spotify account '{self.user_label}' is not connected — "
                "use Log in with Spotify in the app"
            )
        if _as_aware(account.token_expires_at) > datetime.now(tz=UTC):
            access_token = account.access_token
        else:
            access_token = await self._refresh_and_store(account.refresh_token)

        return spotipy.Spotify(auth=access_token)
