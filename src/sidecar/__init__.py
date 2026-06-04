"""HTTP sidecar (FastAPI) consumed by the Electron desktop app.

The sidecar wraps the existing backend (Spotify client, poller, genre resolver,
DB, downloader) and the pluggable music sources behind a small localhost REST API.
"""
