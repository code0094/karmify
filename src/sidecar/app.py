"""FastAPI sidecar app: localhost REST API for the Electron desktop client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from src.db import repos
from src.sources.base import SearchResult, SourceError
from src.spotify import playlist as spotify_playlist

if TYPE_CHECKING:
    from src.sidecar.context import AppContext

logger = structlog.get_logger()


# ---- I/O models -----------------------------------------------------------


class TrackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    spotify_track_id: str
    track_name: str | None
    artist_name: str | None
    liked_by: str
    detected_genre: str | None
    genre_source: str | None
    assigned_playlist_id: str | None
    downloaded_at: datetime | None
    download_path: str | None


class PlaylistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    genre_key: str
    playlist_id: str
    display_name: str
    emoji: str


class AssignBody(BaseModel):
    playlist_db_id: int


class DownloadBody(BaseModel):
    source: str = "spotify"


class SearchBody(BaseModel):
    query: str
    source: str = "spotify"
    limit: int = 20


class DownloadResultBody(BaseModel):
    result: SearchResult


def get_context(request: Request) -> AppContext:
    """FastAPI dependency: the shared :class:`AppContext`."""
    context: AppContext = request.app.state.context
    return context


def create_app(context: AppContext) -> FastAPI:
    """Build the FastAPI app around an already-constructed context."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.context = context
        logger.info("sidecar.started", sources=list(context.sources))
        try:
            yield
        finally:
            await context.aclose()
            logger.info("sidecar.stopped")

    app = FastAPI(title="AUX DJ Sidecar", lifespan=lifespan)

    # The sidecar listens on a fixed localhost port and has no authentication,
    # so any page in the user's browser could otherwise drive it (downloads,
    # playlist writes) — CORS alone does not help, since simple requests are
    # sent before the response is rejected. Block foreign browser origins here.
    allowed_origins = context.settings.allowed_origins()
    auth_token = context.settings.sidecar_auth_token

    @app.middleware("http")
    async def guard_requests(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path == "/health":  # liveness probe for the Electron main process
            return await call_next(request)

        if auth_token:
            if request.headers.get("x-aux-token") != auth_token:
                logger.warning("sidecar.token_rejected", path=request.url.path)
                return JSONResponse(status_code=401, content={"detail": "Invalid token"})
            return await call_next(request)

        # No token configured: fall back to origin filtering. "null" has to be
        # accepted for the packaged renderer (file://), but note that a
        # sandboxed iframe on any site presents the same opaque origin — which
        # is exactly why the token is the supported setup.
        origin = request.headers.get("origin")
        if origin is not None and origin != "null" and origin not in allowed_origins:
            logger.warning("sidecar.origin_rejected", origin=origin, path=request.url.path)
            return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
        return await call_next(request)

    # Electron renderer (file:// or the Vite dev server) calls us cross-origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health(ctx: AppContext = Depends(get_context)) -> dict[str, object]:
        return {"status": "ok", "sources": list(ctx.sources)}

    @app.get("/tracks", response_model=list[TrackOut])
    async def list_tracks(
        genre: str | None = None,
        liked_by: str | None = None,
        only_undownloaded: bool = False,
        limit: int = 200,
        ctx: AppContext = Depends(get_context),
    ) -> list[TrackOut]:
        async with ctx.session_factory() as session:
            tracks = await repos.list_tracks(
                session,
                genre=genre,
                liked_by=liked_by,
                only_undownloaded=only_undownloaded,
                limit=limit,
            )
        return [TrackOut.model_validate(t) for t in tracks]

    @app.get("/playlists", response_model=list[PlaylistOut])
    async def list_playlists(ctx: AppContext = Depends(get_context)) -> list[PlaylistOut]:
        async with ctx.session_factory() as session:
            playlists = await repos.get_all_playlists(session)
        return [PlaylistOut.model_validate(p) for p in playlists]

    @app.post("/likes/fetch")
    async def fetch_likes(ctx: AppContext = Depends(get_context)) -> dict[str, int]:
        new_count = await ctx.fetch_likes()
        return {"new": new_count}

    @app.post("/tracks/{track_id}/assign")
    async def assign_track(
        track_id: int,
        body: AssignBody,
        ctx: AppContext = Depends(get_context),
    ) -> dict[str, bool]:
        async with ctx.session_factory() as session:
            track = await repos.get_track_by_id(session, track_id)
            if track is None:
                raise HTTPException(status_code=404, detail="Track not found")
            playlist = await repos.get_playlist_by_id(session, body.playlist_db_id)
            if playlist is None:
                raise HTTPException(status_code=404, detail="Playlist not found")

            client = ctx.spotify_clients.get(track.liked_by)
            if client is None:
                raise HTTPException(status_code=400, detail="No Spotify client for user")
            sp = await client.get_client()
            added = await spotify_playlist.move_track(
                sp,
                track.spotify_track_id,
                from_playlist=track.assigned_playlist_id,
                to_playlist=playlist.playlist_id,
            )
            await repos.assign_track_to_playlist(
                session, track_id, playlist.playlist_id, track.liked_by
            )
        return {"added": added}

    @app.post("/tracks/{track_id}/download")
    async def download_track(
        track_id: int,
        body: DownloadBody,
        ctx: AppContext = Depends(get_context),
    ) -> dict[str, str]:
        try:
            path = await ctx.download_liked_track(track_id, source=body.source)
        except SourceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"path": str(path)}

    @app.post("/sources/search", response_model=list[SearchResult])
    async def search_sources(
        body: SearchBody,
        ctx: AppContext = Depends(get_context),
    ) -> list[SearchResult]:
        try:
            return await ctx.search_sources(body.query, source=body.source, limit=body.limit)
        except SourceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/sources/download")
    async def download_result(
        body: DownloadResultBody,
        ctx: AppContext = Depends(get_context),
    ) -> dict[str, str]:
        try:
            path = await ctx.download_result(body.result)
        except SourceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"path": str(path)}

    return app


def run() -> None:
    """Entrypoint: build the context from settings and serve via uvicorn."""
    import uvicorn

    from src.config import get_settings
    from src.sidecar.context import AppContext
    from src.utils.logging import setup_logging

    settings = get_settings()
    setup_logging(settings.log_level)
    context = AppContext(settings)
    app = create_app(context)
    uvicorn.run(app, host=settings.sidecar_host, port=settings.sidecar_port)


if __name__ == "__main__":
    run()
