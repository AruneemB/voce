# Voce

A personal text-to-speech companion for [Quanta Magazine](https://www.quantamagazine.org). Voce ingests RSS feeds from Quanta's Physics, Mathematics, Biology, and Computer Science sections, cleans the article HTML into narration-ready prose, and synthesizes it to MP3 via ElevenLabs — all served through a localhost-only FastAPI server with a browser UI.

---

## Features

- **RSS ingestion** — polls four Quanta Magazine feeds on a configurable interval
- **Article enrichment** — strips HTML, converts LaTeX notation to spoken form, builds a narration preamble
- **TTS synthesis** — chunks long articles and assembles them via ElevenLabs into cached MP3s
- **Read-only API** — FastAPI endpoints for sections, articles, topics, full-text search, and pagination
- **Localhost-only** — middleware hard-rejects any non-loopback `Host` header
- **Browser UI** — three-column layout with section sidebar, article list, and reading pane (in progress)
- **Reading state** — per-article unread / queued / listened tracking persisted in SQLite
- **Background scheduler** — APScheduler runs feed refresh and audio cache sweep automatically

---

## Tech Stack

| Layer | Library |
|-------|---------|
| Web framework | FastAPI + Uvicorn |
| Database | SQLite (stdlib `sqlite3`, no ORM), FTS5 |
| Feed parsing | feedparser + httpx |
| HTML parsing | BeautifulSoup4 + lxml |
| TTS | ElevenLabs SDK |
| Audio metadata | mutagen |
| Scheduling | APScheduler |
| Logging | loguru |
| Config | python-dotenv |
| Testing | pytest + FastAPI TestClient |

---

## Requirements

- Python 3.11+
- An [ElevenLabs](https://elevenlabs.io) API key

---

## Setup

```bash
# 1. Clone and create a virtual environment
git clone https://github.com/AruneemB/voce.git
cd voce
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -e .

# 3. Configure environment
cp .env.example .env
# Edit .env and set ELEVENLABS_API_KEY=<your key>

# 4. Start the server
python -m voce
```

The server binds to `127.0.0.1:8765` by default. Open `http://127.0.0.1:8765` in a browser.

### CLI flags

```
python -m voce [OPTIONS]

  --host HOST            Bind address (default: 127.0.0.1)
  --port PORT            Port (default: 8765)
  --log-level LEVEL      Log level: DEBUG | INFO | WARNING | ERROR
  --refresh-now          Run a feed refresh and exit (no server)
  --sweep-cache          Sweep expired audio cache and exit (no server)
  --no-browser           Do not auto-open a browser tab on startup
```

---

## API Reference

All endpoints require `Host: 127.0.0.1:<port>` or `Host: localhost:<port>`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serves the browser UI |
| `GET` | `/api/sections` | All sections with unread counts |
| `GET` | `/api/articles` | Paginated article list — filter by `section`, `status`, `topic`, `q` |
| `GET` | `/api/articles/{id}` | Article detail with `body_text` |
| `GET` | `/api/topics` | Topics with article counts |
| `GET` | `/api/search` | FTS5 full-text search (falls back to `LIKE`) |
| `POST` | `/api/refresh` | Trigger a feed refresh |
| `POST` | `/api/articles/{id}/audio` | Request TTS synthesis (returns 202 while pending) |
| `GET` | `/api/articles/{id}/audio/status` | Check synthesis status and cache URL |
| `GET` | `/api/articles/{id}/audio/stream` | Stream the cached MP3 |
| `POST` | `/api/articles/{id}/state` | Update reading state (`unread` / `queued` / `listened`) |
| `GET` | `/api/queue` | Articles in the listening queue |

---

## Running Tests

```bash
pytest tests/ -v
```

108 tests pass across all completed phases.

---

## Project Structure

```
voce/
├── __init__.py          # Package version
├── __main__.py          # CLI entry point (argparse + uvicorn)
├── config.py            # Settings dataclass, dotenv loading
├── db.py                # SQLite connection, schema DDL, bootstrap
├── models.py            # Article, ReadingState, AudioCache dataclasses
├── exceptions.py        # VoceError hierarchy
├── feeds.py             # RSS ingestion, upsert, refresh_all_feeds
├── article.py           # HTML→prose pipeline, LaTeX substitution, enrich
├── tts.py               # ElevenLabs synthesis, chunk splitting  [stub]
├── cache.py             # Audio cache sweep and stats            [stub]
├── scheduler.py         # APScheduler job setup                  [stub]
├── api.py               # FastAPI app, routes, Pydantic models
└── static/
    ├── index.html       # Browser UI                             [stub]
    ├── app.js           # Frontend JS                            [stub]
    └── styles.css       # Custom styles                          [stub]
tests/
├── test_skeleton.py     # Module importability (Phase 1)
├── test_config.py       # Settings loading (Phase 2)
├── test_db.py           # Schema bootstrap and constraints (Phase 2)
├── test_feeds.py        # RSS parsing and upsert (Phase 3)
├── test_article.py      # HTML cleaning and LaTeX substitution (Phase 4)
└── test_api.py          # FastAPI routes (Phase 5)
```

---

## Build Progress

| # | Phase | Status | Tests |
|---|-------|--------|-------|
| 1 | Skeleton | Done | 11 passing |
| 2 | DB and Config | Done | 5 passing |
| 3 | Feed Ingestion | Done | 7 passing |
| 4 | Article Cleanup | Done | 11 passing |
| 5 | API (Read-Only) | Done | 8 passing |
| 6 | Frontend (Browsing) | Pending | manual |
| 7 | TTS | Pending | 9 tests |
| 8 | Frontend (Listening) | Pending | 4 tests |
| 9 | State and Scheduling | Pending | 7 tests |
| 10 | Polish | Pending | 4 tests |

### What remains

**Phase 6 — Frontend (Browsing)**
Populate `voce/static/index.html`, `app.js`, and `styles.css`. Three-column layout using Tailwind + htmx. Section sidebar, article card list with infinite scroll, article detail pane, debounced search, and state filter buttons.

**Phase 7 — TTS**
Implement `voce/tts.py` (`chunk_text`, `synthesize_chunk`, `synthesize_article`) and `voce/cache.py` (`sweep_expired_cache`, `get_cache_stats`).

**Phase 8 — Frontend (Listening)**
Wire audio player UI into the article detail pane. Add `/api/articles/{id}/audio` synthesis and status endpoints. Poll for synthesis completion and surface Quanta's own narration when available.

**Phase 9 — State and Scheduling**
Add `POST /api/articles/{id}/state` and `GET /api/queue` endpoints. Implement `voce/scheduler.py` with APScheduler feed refresh and daily cache sweep. Wire state toggle buttons into the frontend.

**Phase 10 — Polish**
`GET /api/search` with FTS5 and `LIKE` fallback. Dark mode toggle (localStorage persistence). `--refresh-now` and `--sweep-cache` CLI flags. Loguru file handler (`data/voce.log`). `safeFetch` wrapper with error toasts across all frontend fetch calls.

---

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `ELEVENLABS_API_KEY` | — | **Required.** ElevenLabs API key |
| `ELEVENLABS_VOICE_ID` | `21m00Tcm4TlvDq8ikWAM` | Voice ID (Rachel) |
| `ELEVENLABS_MODEL_ID` | `eleven_turbo_v2_5` | Model ID |
| `HOST` | `127.0.0.1` | Server bind address |
| `PORT` | `8765` | Server port |
| `AUDIO_CACHE_TTL_DAYS` | `30` | Days before cached audio expires |
| `FEED_REFRESH_MINUTES` | `30` | Feed poll interval (minimum 30) |
| `LOG_LEVEL` | `INFO` | Log level: DEBUG / INFO / WARNING / ERROR |

---

## Invariants

- Server binds to `127.0.0.1` only; middleware returns 403 for any other `Host` header.
- No ORM — all DB access uses raw parameterized SQL via stdlib `sqlite3`.
- No async SQLite — DB calls are synchronous, run via thread-pool executor from async routes.
- All SQL keywords are uppercase; SQL is never built with f-strings or `.format()`.
- All logging uses loguru; `print()` is not used after Phase 1.
