# 🎧 Karmify

**A multi-source music acquisition and library tool for DJs.**

Karmify watches the Spotify "Liked Songs" of a DJ crew, figures out each track's
genre through a cascade of music APIs, and lets you pull the actual audio — in
lossless where possible — from **Spotify, Soulseek, or Bandcamp**, dropping
finished, tagged files straight into a folder your Rekordbox/Serato library
watches.

It started as a fix for one problem every selector knows: *Liked Songs becomes a
genre soup, and you end up hand-sorting tracks the night before a gig.*

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-sidecar-009688?logo=fastapi&logoColor=white">
  <img alt="Electron" src="https://img.shields.io/badge/Electron-desktop-47848F?logo=electron&logoColor=white">
  <img alt="React" src="https://img.shields.io/badge/React-Vite-61DAFB?logo=react&logoColor=black">
</p>

---

## What it does

- **Watches likes** across multiple Spotify accounts and pulls in new tracks on demand.
- **Resolves genre** through a waterfall — Spotify artist genres → Discogs → Last.fm
  — and normalises the result to your own genre keys via an alias table.
- **Finds the audio** across three sources behind one interface, so you can prefer
  a FLAC from Soulseek over a transcoded Spotify rip.
- **Builds your library** by copying finished, tagged files into a watched folder
  that Rekordbox or Serato imports.
- **Sorts into playlists** — assign a track to a genre playlist and it's pushed
  back to Spotify, with an undo window.

## Architecture

Karmify is a thin **Electron** desktop app over a **Python sidecar**. All the real
work — Spotify, genre resolution, downloading, the database — lives in the sidecar,
so the UI stays disposable and the backend can also run headless on a server.

```
┌──────────────── Electron (desktop) ─────────────────┐
│ Renderer (React + Vite): library, player, search    │
│ Main (Node): window + spawns the Python sidecar      │
└───────────────┬──────────────────────────────────────┘
                │ HTTP (localhost / SSH tunnel)
┌───────────────▼──── Python sidecar (FastAPI) ────────┐
│ Spotify client · poller · genre resolver · DB        │
│ MusicSource:  Spotify (zotify) · Soulseek · Bandcamp │
│ Library manager → watched folder → Rekordbox/Serato  │
└──────────────────────────────────────────────────────┘
```

Every download backend implements one `MusicSource` interface
(`search()` / `download()`), which mirrors the waterfall pattern used by the genre
resolver. Adding a fourth source is a single new class.

## Sources

| Source | How it gets audio | Format | Notes |
|--------|-------------------|--------|-------|
| **Spotify** | Metadata → match → download via [zotify](https://github.com/Googolplexed0/zotify) | mp3 / ogg | Uses a dedicated account; needs `ffmpeg`. |
| **Soulseek** | [slskd](https://github.com/slskd/slskd) daemon over its REST API | **FLAC** & others | P2P; lossless-first ranking. |
| **Bandcamp** | Antidetect browser ([nodriver](https://github.com/ultrafunkamsterdam/nodriver)) drives the free *name-your-price* flow; the emailed link is read over IMAP | **FLAC** | Artist-sanctioned free/NYP releases only. |

## Tech stack

- **Python 3.11+** — async throughout (`asyncio`, `asyncpg`, `aiohttp`)
- **FastAPI + Uvicorn** — the localhost sidecar API
- **SQLAlchemy 2.0 + PostgreSQL** — async ORM and storage
- **aiogram 3** — optional Telegram channel for "new like" pushes
- **Electron + React + Vite + TypeScript** — desktop UI
- **Pydantic v2 / structlog / Ruff / pytest** — config, logging, lint, tests

## Project layout

```
src/
├── config.py            # Pydantic settings
├── sidecar/             # FastAPI app + AppContext wiring
├── sources/             # MusicSource interface + Spotify/Soulseek/Bandcamp
├── library/             # copy finished tracks into the DJ library folder
├── spotify/             # client, poller, playlist, zotify downloader
├── genre/               # resolver waterfall + genre→playlist mapper
├── db/                  # models, repositories, async engine
└── bot/                 # optional Telegram interface
electron/                # desktop app (main process + React renderer)
tests/                   # pytest suite
```

## Getting started

### Backend (sidecar)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .                 # needs git + ffmpeg on the system
cp .env.example .env             # then fill in credentials
python -m src.sidecar.app        # serves on 127.0.0.1:8765
```

### Desktop app

```bash
cd electron
npm install
npm run dev                      # launches Electron, spawns the sidecar
```

The renderer talks to the sidecar over `localhost`. When the backend runs on a
server, point the app at it through an SSH tunnel:

```bash
ssh -L 8765:127.0.0.1:8765 user@your-server
```

## Configuration

All configuration is environment variables (see `.env.example`). The essentials:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | `postgresql+asyncpg://…` connection string |
| `SPOTIFY_CLIENT_ID` / `_SECRET` | Spotify app credentials |
| `*_SPOTIFY_REFRESH_TOKEN` | per-account refresh tokens |
| `DISCOGS_USER_TOKEN`, `LASTFM_API_KEY` / `_SECRET` | genre resolution |
| `SLSKD_URL` / `SLSKD_API_KEY` | Soulseek source (optional) |
| `BANDCAMP_MAIL_*` | mailbox that receives Bandcamp download links |
| `DOWNLOAD_DIR`, `LIBRARY_DIR` | where audio lands and the watched library folder |

## Development

```bash
pytest -q                        # test suite
ruff check . && ruff format .    # lint + format (line length 99)
```

## Roadmap

- [x] Multi-source backend behind one `MusicSource` interface
- [x] FastAPI sidecar + Electron shell
- [ ] Deep Rekordbox/Serato integration (write to their libraries, not just a folder)
- [ ] CapSolver integration for the Bandcamp CAPTCHA edge case
- [ ] One-click packaged desktop build

## Disclaimer

Karmify is built for **personal use by working DJs** managing music they have a
right to use. Bandcamp downloads are limited to free / name-your-price releases the
artist has chosen to give away. Spotify access uses the official Web API; audio
retrieval and Soulseek use are intended for private, fair-use, and educational
purposes. Respect the terms of service of every platform you connect, and support
the artists you play.
