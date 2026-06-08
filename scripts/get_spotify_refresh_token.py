"""One-off helper: obtain a Spotify Web API refresh token for one account.

Run this LOCALLY (it needs a browser), once per account (karma, stress303, ...):

    pip install spotipy
    python scripts/get_spotify_refresh_token.py <CLIENT_ID> <CLIENT_SECRET>

It prints an authorize URL. Open it, log in with the *target* account, approve,
then paste the full URL you were redirected to back into the prompt. The script
prints the refresh token — put it in .env as <ACCOUNT>_SPOTIFY_REFRESH_TOKEN.

The redirect URI must match one registered in your Spotify app
(http://127.0.0.1:8888/callback by default).
"""

from __future__ import annotations

import sys

from spotipy.oauth2 import SpotifyOAuth

SCOPE = "user-library-read playlist-modify-public playlist-modify-private"
REDIRECT_URI = "http://127.0.0.1:8888/callback"


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: python scripts/get_spotify_refresh_token.py CLIENT_ID CLIENT_SECRET")
        raise SystemExit(1)

    client_id, client_secret = sys.argv[1], sys.argv[2]
    oauth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        open_browser=False,
        cache_handler=None,
    )

    print("\n1) Open this URL, log in with the target account, and approve:\n")
    print(oauth.get_authorize_url())
    print()
    redirected = input("2) Paste the full URL you were redirected to:\n> ").strip()

    code = oauth.parse_response_code(redirected)
    token_info = oauth.get_access_token(code, as_dict=True, check_cache=False)

    print("\n=== REFRESH TOKEN (put in .env) ===")
    print(token_info["refresh_token"])


if __name__ == "__main__":
    main()
