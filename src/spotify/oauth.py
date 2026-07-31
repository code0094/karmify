"""Spotify authorization-code flow: "Log in with Spotify" instead of pasted tokens.

Refresh tokens used to be copied into .env by hand, which meant a token could
only be obtained by running a helper script and pasting its output. Here the
user authorizes in a browser and the tokens land straight in the database.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from spotipy.oauth2 import SpotifyOAuth

from src.spotify.client import SCOPES

if TYPE_CHECKING:
    from src.config import Settings

logger = structlog.get_logger()

#: A pending authorization is useless after this long; state entries expire so a
#: stale or forged callback cannot be replayed later.
STATE_TTL_SEC = 600


class OAuthError(Exception):
    """Raised when an authorization attempt cannot be completed."""


@dataclass(frozen=True)
class PendingAuth:
    user_label: str
    created_at: float


class SpotifyAuthFlow:
    """Builds authorization URLs and redeems the codes Spotify sends back.

    The pending-state map lives in memory on purpose: an authorization that does
    not finish within minutes should not survive a restart anyway.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pending: dict[str, PendingAuth] = {}

    def _oauth(self) -> SpotifyOAuth:
        if not self._settings.spotify_client_id or not self._settings.spotify_client_secret:
            raise OAuthError(
                "Spotify app credentials are not configured "
                "(SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET)"
            )
        return SpotifyOAuth(
            client_id=self._settings.spotify_client_id,
            client_secret=self._settings.spotify_client_secret,
            redirect_uri=self._settings.spotify_redirect_uri,
            scope=SCOPES,
        )

    def _prune(self) -> None:
        cutoff = time.monotonic() - STATE_TTL_SEC
        for state, pending in list(self._pending.items()):
            if pending.created_at < cutoff:
                del self._pending[state]

    def start(self, user_label: str) -> str:
        """Return the Spotify URL to send the user to."""
        self._prune()
        oauth = self._oauth()  # fail before minting state when unconfigured
        state = secrets.token_urlsafe(32)
        self._pending[state] = PendingAuth(user_label=user_label, created_at=time.monotonic())
        logger.info("spotify_auth.started", user=user_label)
        return str(oauth.get_authorize_url(state=state))

    def redeem(self, *, code: str, state: str) -> tuple[str, dict[str, Any]]:
        """Exchange an authorization code for tokens.

        Returns:
            The user label this authorization was started for, and the token
            payload from Spotify.

        Raises:
            OAuthError: If the state is unknown or expired — which is what makes
                a forged callback useless.
        """
        self._prune()
        pending = self._pending.pop(state, None)  # single use
        if pending is None:
            raise OAuthError("Unknown or expired authorization request")

        token_info = self._oauth().get_access_token(code, as_dict=True, check_cache=False)
        if not token_info or not token_info.get("refresh_token"):
            raise OAuthError("Spotify did not return a refresh token")

        logger.info("spotify_auth.completed", user=pending.user_label)
        return pending.user_label, dict(token_info)
