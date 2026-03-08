# AUX DJ Bot — Spotify → Telegram Genre Sorter

## Project Overview

Telegram-бот для промо-команды **AUX MASTERS** для двух диджеев(пока что)
Мониторит лайки обоих участников в Spotify, определяет жанр трека через каскад API,
предлагает добавить в жанровый плейлист через inline-кнопки в общем Telegram-чате.

**Основная боль:** мешанина треков в Liked Songs, ручной подбор перед гигами.

## Architecture

```
┌─────────────┐     polling 30s      ┌──────────────┐
│  Spotify API │◄────────────────────│   Poller      │
│  (2 accounts)│                     │  (asyncio)    │
└─────────────┘                      └──────┬───────┘
                                            │ new like detected
                                            ▼
                                    ┌───────────────┐
                                    │ Genre Resolver │
                                    │  (waterfall)   │
                                    └──────┬────────┘
                                           │
                          ┌────────────────┼────────────────┐
                          ▼                ▼                ▼
                   Spotify Artist    Discogs API      Last.fm Tags
                     genres[]       genre+style      track.getTopTags
                          │                │                │
                          └────────┬───────┘────────────────┘
                                   ▼
                           ┌──────────────┐
                           │ Genre Mapper  │
                           │ → playlist_id │
                           └──────┬───────┘
                                  ▼
                          ┌───────────────┐     inline buttons
                          │ Telegram Bot  │◄──────────────────── User
                          │  (aiogram 3)  │
                          └──────┬────────┘
                                 │ callback: playlist chosen
                                 ▼
                          ┌──────────────┐
                          │ Spotify API   │
                          │ POST playlist │
                          └──────────────┘
```

## Tech Stack

- **Python 3.11+**
- **aiogram 3.x** — Telegram bot framework (async)
- **spotipy** — Spotify Web API wrapper
- **python3-discogs-client** — Discogs API
- **pylast** — Last.fm API
- **SQLAlchemy 2.0 + asyncpg** — async PostgreSQL ORM
- **APScheduler** или **asyncio loop** — polling scheduler
- **Pydantic v2** — settings, validation
- **Docker + docker-compose** — deployment

## Project Structure

```
aux-dj-bot/
├── CLAUDE.md
├── .claude/
│   ├── skills/
│   │   ├── spotify-integration/SKILL.md
│   │   ├── genre-resolver/SKILL.md
│   │   └── telegram-bot-aiogram/SKILL.md
│   └── hooks/
│       ├── pre-commit-lint.sh
│       └── post-test.sh
├── pyproject.toml
├── docker-compose.yml
├── Dockerfile
├── alembic/
│   └── versions/
├── src/
│   ├── __init__.py
│   ├── config.py              # Pydantic Settings (env vars)
│   ├── main.py                # entrypoint: start bot + poller
│   ├── db/
│   │   ├── __init__.py
│   │   ├── engine.py          # async engine, session factory
│   │   ├── models.py          # SQLAlchemy models
│   │   └── repos.py           # repository pattern queries
│   ├── spotify/
│   │   ├── __init__.py
│   │   ├── client.py          # spotipy wrapper, token refresh
│   │   ├── poller.py          # liked tracks polling loop
│   │   └── playlist.py        # add to playlist logic
│   ├── genre/
│   │   ├── __init__.py
│   │   ├── resolver.py        # waterfall: spotify → discogs → lastfm → manual
│   │   ├── spotify_genres.py  # fetch artist genres from Spotify
│   │   ├── discogs_lookup.py  # search release, extract genre+style
│   │   ├── lastfm_tags.py     # track.getTopTags via pylast
│   │   └── mapper.py          # genre string → playlist_id mapping
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── app.py             # aiogram Dispatcher setup
│   │   ├── handlers/
│   │   │   ├── __init__.py
│   │   │   ├── callbacks.py   # inline button callbacks
│   │   │   ├── commands.py    # /start, /playlists, /stats
│   │   │   └── errors.py      # error handler
│   │   ├── keyboards.py       # InlineKeyboardMarkup builders
│   │   └── notifications.py   # send new-like messages to chat
│   └── utils/
│       ├── __init__.py
│       └── logging.py         # structured logging (structlog)
├── tests/
│   ├── conftest.py
│   ├── test_poller.py
│   ├── test_genre_resolver.py
│   ├── test_mapper.py
│   └── test_bot_callbacks.py
├── scripts/
│   ├── init_playlists.py      # one-time: create genre playlists
│   └── migrate_likes.py       # backfill existing likes
└── .env.example
```

## Database Schema

```sql
-- Spotify OAuth tokens for both users
CREATE TABLE spotify_accounts (
    id SERIAL PRIMARY KEY,
    user_label VARCHAR(50) UNIQUE NOT NULL,  -- 'karma' | 'stress303'
    spotify_user_id VARCHAR(255) NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    token_expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Genre-to-playlist mapping
CREATE TABLE genre_playlists (
    id SERIAL PRIMARY KEY,
    genre_key VARCHAR(100) UNIQUE NOT NULL,   -- normalized: 'hardgroove', 'jungle', etc.
    playlist_id VARCHAR(255) NOT NULL,         -- Spotify playlist ID
    display_name VARCHAR(100) NOT NULL,        -- button label: '🔊 Hardgroove'
    emoji VARCHAR(10) DEFAULT '🎵'
);

-- Every processed like
CREATE TABLE liked_tracks (
    id SERIAL PRIMARY KEY,
    spotify_track_id VARCHAR(255) NOT NULL,
    track_name VARCHAR(500),
    artist_name VARCHAR(500),
    liked_by VARCHAR(50) NOT NULL,             -- FK → spotify_accounts.user_label
    liked_at TIMESTAMPTZ,
    detected_genre VARCHAR(100),
    genre_source VARCHAR(20),                  -- 'spotify' | 'discogs' | 'lastfm' | 'manual'
    assigned_playlist_id VARCHAR(255),
    assigned_by VARCHAR(50),                   -- who pressed the button
    assigned_at TIMESTAMPTZ,
    telegram_message_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(spotify_track_id, liked_by)
);

-- Alias table for fuzzy genre → genre_key mapping
CREATE TABLE genre_aliases (
    id SERIAL PRIMARY KEY,
    alias VARCHAR(200) UNIQUE NOT NULL,        -- 'dark techno', 'industrial techno', etc.
    genre_key VARCHAR(100) NOT NULL            -- FK → genre_playlists.genre_key
);
```

## Coding Standards

### General
- **Language:** Python 3.11+, type hints everywhere
- **Async-first:** all I/O is async (aiohttp, asyncpg, aiogram)
- **No bare `except:`** — always catch specific exceptions
- **Pydantic** for all config, API responses, validation
- **Docstrings:** Google-style for all public functions
- **Logging:** structlog, structured JSON in production

### Formatting & Linting
- **Ruff** — linter + formatter (replaces black, isort, flake8)
- Config in `pyproject.toml`, line length 99
- Run `ruff check --fix . && ruff format .` before every commit

### Testing
- **pytest + pytest-asyncio** for all tests
- Fixtures in `conftest.py` for DB, Spotify mocks, bot mocks
- Mock external APIs (Spotify, Discogs, Last.fm) — never hit real APIs in tests
- Minimum coverage: 80% for `src/genre/` and `src/spotify/`

### Git
- Conventional commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`
- Branch per feature: `feat/genre-resolver`, `fix/token-refresh`
- Squash merge to `main`

## Environment Variables

```env
# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=         # shared chat ID

# Spotify — Account 1 (karma)
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REDIRECT_URI=http://localhost:8888/callback
KARMA_SPOTIFY_REFRESH_TOKEN=

# Spotify — Account 2 (stress303)
STRESS303_SPOTIFY_REFRESH_TOKEN=

# Discogs
DISCOGS_USER_TOKEN=

# Last.fm
LASTFM_API_KEY=
LASTFM_API_SECRET=

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/aux_dj_bot

# App
POLL_INTERVAL_SECONDS=30
LOG_LEVEL=INFO
```

## Key Implementation Notes

### Spotify Token Refresh
Spotipy handles auto-refresh, but we store tokens in DB for two accounts.
Use `SpotifyOAuth` with `scope="user-library-read playlist-modify-public playlist-modify-private"`.
Wrap in a class that lazy-refreshes and updates DB on each refresh.

### Genre Resolution Waterfall
```python
async def resolve_genre(track_id: str, artist_name: str, track_name: str) -> GenreResult:
    # Level 1: Spotify artist genres
    result = await spotify_genres.get_genres(track_id)
    if result.has_match():
        return result

    # Level 2: Discogs search (genre + style)
    result = await discogs_lookup.search(artist_name, track_name)
    if result.has_match():
        return result

    # Level 3: Last.fm tags
    result = await lastfm_tags.get_top_tags(artist_name, track_name)
    if result.has_match():
        return result

    # Level 4: manual — return empty, bot will show full playlist list
    return GenreResult(genre=None, source="manual")
```

### Genre Mapper
Uses `genre_aliases` table for fuzzy matching. The mapper normalizes
incoming genre strings (lowercase, strip whitespace) and looks up aliases.
Example mappings:
- `"dark techno"`, `"industrial techno"`, `"peak time techno"` → `hardgroove`
- `"acid"`, `"acid techno"`, `"303"` → `acid`
- `"jungle"`, `"ragga jungle"`, `"breakbeat"` → `jungle`
- `"electro"`, `"new electro"`, `"electro house"` → `electro`

### Telegram Message Format
```
🎵 Новый лайк от @karma
🎧 ROD — Akephale
📀 Label: Planet Rhythm (if available from Discogs)
🏷 Detected: hardgroove (via discogs)

Добавить в плейлист:
[🔊 Hardgroove ✨] [⚡ Rave Techno] [🔌 Electro] [📋 Другой...]
```
The suggested playlist (from genre resolver) gets ✨ marker.
"Другой..." expands to full list of all playlists.

### Deduplication
Before adding to playlist, check `liked_tracks` table AND call
Spotify's playlist tracks endpoint to verify track isn't already there.

### Polling Strategy
- Poll `GET /me/tracks?limit=5` every 30 seconds per account
- Compare with last known `liked_at` timestamp from DB
- Process only genuinely new tracks
- Handle rate limits with exponential backoff

## Commands for Development

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run
python -m src.main

# Test
pytest -v --cov=src/genre --cov=src/spotify

# Lint
ruff check --fix . && ruff format .

# DB migrations
alembic revision --autogenerate -m "description"
alembic upgrade head

# Docker
docker-compose up -d --build
```

## DO NOT

- Do NOT hardcode Spotify tokens — always use env vars and DB storage
- Do NOT make synchronous HTTP calls — everything async
- Do NOT skip type hints — mypy strict mode is the goal
- Do NOT commit `.env` files
- Do NOT call real external APIs in tests
- Do NOT ignore rate limits from Spotify (429) or Discogs (60/min)
