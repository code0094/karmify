# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AUX DJ Bot** — Telegram bot for the AUX MASTERS DJ duo (`karma`, `stress303`).
Scheduled poller pulls each user's Spotify Liked Songs, runs a genre-resolution waterfall
(Spotify → Discogs → Last.fm), and posts the new track to a shared Telegram chat with
inline buttons that add it to the appropriate genre playlist on Spotify.

## Common Commands

```bash
# Setup (Python 3.11+)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run the bot (requires .env + Postgres)
python -m src.main

# Tests
pytest                                    # all
pytest tests/test_genre_resolver.py       # one file
pytest tests/test_genre_resolver.py::test_resolve_genre_spotify_match   # one test
pytest -v --cov=src/genre --cov=src/spotify

# Lint + format (run before committing)
ruff check --fix . && ruff format .

# Type check (mypy is configured strict)
mypy src

# Docker (full stack with Postgres)
docker-compose up -d --build
```

## Architecture

### Runtime topology

`src/main.py` is the single entrypoint and wires everything together:

1. Loads `Settings` (cached via `@lru_cache`, see `src/config.py`).
2. Builds one async SQLAlchemy engine + `session_factory` (`src/db/engine.py`).
3. Constructs **two** `SpotifyClient` instances keyed by `user_label` (`karma`, `stress303`) — these are the two DJs.
4. Creates aiogram `Bot` + `Dispatcher`. The dispatcher's routers are constructed via factory functions (`setup_command_router`, `setup_callback_router`) so dependencies (session factory, Spotify clients) are closed over rather than passed through middleware.
5. Schedules `poll_all_users` on `APScheduler` `CronTrigger`s parsed from `POLL_SCHEDULE` (UTC, e.g. `08:00,20:00`).
6. Starts `dp.start_polling(bot)` as a task and waits on a shutdown event installed via SIGTERM/SIGINT signal handlers. On shutdown the scheduler stops, the polling task is cancelled, the bot session closes, and the engine is disposed.

The "glue" is the `on_new_track` closure defined in `main.py`: poller → genre resolver → DB update → Telegram notification. The poller doesn't know about Telegram or genres; it just calls back per new track.

### Async / sync boundary

All third-party SDKs in this project (`spotipy`, `python3-discogs-client`, `pylast`) are **synchronous**. Every call to them must be wrapped in `asyncio.to_thread(...)` to avoid blocking the event loop. The codebase already does this consistently — match the pattern when adding new external API calls.

### Genre resolution waterfall

`src/genre/resolver.py::resolve_genre` runs four levels in order, returning a `GenreResult` as soon as one yields a `genre_key`:

1. **Spotify artist genres** (`spotify_genres.get_artist_genres`) — fetches the track, then its artists, collects `genres[]`.
2. **Discogs genre + style** (`discogs_lookup.search_genre`) — first release match, concatenates `genres + styles`.
3. **Last.fm top tags** (`lastfm_tags.get_top_tags`) — only tags with `weight > 30`.
4. **manual** — returns `genre_key=None`, source `"manual"`. The bot then shows the full playlist list instead of a suggestion.

The Discogs **label** is fetched once up front (regardless of which waterfall level matches) and attached to the result for display in the Telegram message.

Each level's raw genre strings are passed through `mapper.map_to_genre_key`, which looks them up in the `genre_aliases` table (lowercase + stripped). **Aliases are data, not code** — to add new mappings, insert rows into `genre_aliases`, don't touch Python.

### Database layer

- SQLAlchemy 2.0 async with `asyncpg`. Session factory uses `expire_on_commit=False` so ORM objects remain usable after commit (relied on by the poller, which returns `track` after `commit()` and passes it to the callback).
- All queries live in `src/db/repos.py` (repository pattern). Add new queries there, not inline.
- `get_track_for_update` uses `SELECT ... FOR UPDATE` — used by the assign callback to prevent two users racing to assign the same track to different playlists. Preserve this when modifying `handle_assign`.
- **No Alembic migrations exist yet** despite the Dockerfile copying `alembic/` and `alembic.ini`. The Docker build will fail on `COPY alembic/ alembic/` until that directory is created. If you set up migrations, this is the gap to close.
- Tables are declared in `src/db/models.py`. The schema is `spotify_accounts`, `genre_playlists`, `liked_tracks`, `genre_aliases` with a unique constraint on `(spotify_track_id, liked_by)` for dedup.

### Spotify token handling

`SpotifyClient.get_client()` does the dance:
- Try DB row for the user; if present and `token_expires_at` is in the future, use the cached `access_token`.
- Otherwise refresh: prefer the DB's `refresh_token`, fall back to the env var (`KARMA_SPOTIFY_REFRESH_TOKEN` / `STRESS303_SPOTIFY_REFRESH_TOKEN`) for the first-ever run when no DB row exists yet. Persist new tokens via `repos.update_tokens`.

The `user_label` → env var mapping is hardcoded in `_get_refresh_token`. Adding a third DJ requires adding a new env var, an entry to that branch, and a third `SpotifyClient` in `main.py`.

### Telegram callback data format

Telegram limits callback data to **64 bytes**, so the encoding is intentionally terse (`src/bot/keyboards.py`, `src/bot/handlers/callbacks.py`):

- `a:{track_db_id}:{playlist_db_id}` — assign track to playlist
- `e:{track_db_id}` — expand to full playlist list ("Другой...")
- `r:{track_db_id}` — reassign (only valid for 24h after `assigned_at`)

IDs are **DB primary keys**, not Spotify IDs (Spotify IDs are 22 chars and would blow the budget). When adding new callbacks, use single-letter prefixes and integer IDs.

### Deduplication

Two layers, both required:
1. DB unique constraint `(spotify_track_id, liked_by)` — prevents duplicate poll insertion.
2. `spotify_playlist.track_in_playlist` paginates the playlist before adding — prevents adding a track that's already there (e.g. manually added by a DJ).

### Logging

`structlog`. JSON output when `ENVIRONMENT=production`, console-friendly otherwise. Log via `structlog.get_logger()` and pass structured kwargs (e.g. `logger.info("track.assigned", track_id=..., genre=...)`) — don't f-string into the event name.

## Environment Variables

See `.env.example` for the bot itself. Note `docker-compose.yml` additionally requires `POSTGRES_PASSWORD` (no default) and accepts `POSTGRES_USER` / `POSTGRES_DB` (defaults `auxbot` / `aux_dj_bot`). When running via compose, `DATABASE_URL` must point at the `db` service host, not `localhost`.

`POLL_SCHEDULE` is comma-separated `HH:MM` (UTC); validated by `Settings.validate_poll_schedule` at startup, so a malformed value fails fast.

## Conventions

- **Type hints everywhere**, mypy strict. Use `from __future__ import annotations` + `TYPE_CHECKING` blocks for import-cycle avoidance (already standard in this repo).
- **Ruff**, line length 99. Selects: `E,W,F,I,UP,B,SIM,N`.
- **Conventional commits** (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`). Existing history follows this strictly.
- **Async-only I/O**. No blocking calls outside `asyncio.to_thread`.
- **No bare `except:`** — catch the specific exception type. The existing code uses broad `except Exception:` only at top-level boundaries (poller loop, error handler) where the exception is logged via `logger.exception`.
- **Tests mock all external APIs** (Spotify/Discogs/Last.fm). See `tests/conftest.py` for the canonical mocks. Never let a test hit a real API.

## Known Gaps (vs. the design discussion)

These are referenced in past design notes but not in code — be aware before claiming a feature works:

- No `alembic/` directory or migrations (Dockerfile expects them).
- No `scripts/init_playlists.py` or `scripts/migrate_likes.py`.
- No `/health` endpoint.
- No retry/circuit-breaker logic for external APIs — failures just log and return empty.
- No Discogs rate-limit handling (`X-Discogs-Ratelimit-Remaining`).
