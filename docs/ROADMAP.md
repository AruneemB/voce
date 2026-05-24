# Roadmap

Voce is built in ten discrete phases, each with clear acceptance criteria and an automated test suite. This document describes what has been completed, what is in progress, and what lies ahead.

---

## What is complete

### Phase 1 — Project skeleton

The package scaffold, entry point, and initial test harness. Running `pip install -e .` installs Voce and all dependencies. Running `python -m voce` starts the server stub.

### Phase 2 — Database and configuration

The settings system (`config.py`) loads from environment variables with typed defaults. The database layer (`db.py`) bootstraps the full schema — four tables, four indexes, one FTS5 virtual table, three triggers — on first run. The `models.py` dataclasses provide typed representations of every table row.

### Phase 3 — RSS ingestion

The feed ingestion pipeline (`feeds.py`) fetches all four Quanta Magazine sections, parses entries, and upserts articles into the database. Retry logic handles transient network failures with exponential back-off. Re-ingesting known articles is safe and idempotent.

### Phase 4 — Article enrichment

The HTML-to-prose pipeline (`article.py`) converts raw article HTML into clean, narration-ready text. Noise elements are stripped, list structures are converted to natural language, LaTeX mathematical expressions are rendered as spoken equivalents, and an attribution preamble is prepended to every article.

### Phase 5 — Read-only API

The FastAPI application (`api.py`) exposes all browsing endpoints: sections with unread counts, paginated article lists with section/topic/status/full-text filters, article detail including body text, topic listings, and a feed refresh trigger. The `LocalhostOnlyMiddleware` enforces the localhost-only access policy.

### Phase 6 — Browser UI

The single-page frontend (`index.html`, `app.js`, `styles.css`) implements a full browsing experience with a three-column layout:

- **Header** — "Voce" wordmark, tagline "a reading companion for Quanta Magazine", a `<input type="search">` with 300 ms debounced search, and a Refresh button that calls `POST /api/refresh`
- **Left sidebar** (`#sidebar`) — section list (`#section-list`) populated from `/api/sections` with unread badge counts; status filter buttons (`#state-filters`: All, Unread, Queued, Listened); topic dropdown (`#topic-filter`)
- **Article list** — scrollable panel of article cards rendered from `/api/articles`. Each card shows title, author, date, a 200-character summary excerpt, and a colour-coded reading status badge. Infinite scroll is implemented via `IntersectionObserver` watching the `#load-more-sentinel` element.
- **Article detail** (`#article-detail`) — full article view with title, byline, an "Open in Quanta ↗" link, and body text rendered as `<p>` tags split on double newlines. A reserved `#audio-player-section` div is present for the Phase 8 audio player.

Navigation state is maintained via `history.pushState`. On load, `location.hash` is parsed so that `#article/{id}` URLs deep-link directly into an article. Tailwind CSS and htmx are loaded from CDN — no build step is required.

**160 tests pass across Phases 1–6** (52 new tests covering static file serving, all nine required element IDs, CDN tag correctness, JavaScript function definitions, state variable declarations, API call patterns, and all CSS selectors and colour values).

### Phase 7 — TTS synthesis

The ElevenLabs synthesis layer (`tts.py`, `cache.py`) implements the complete audio synthesis pipeline:

- **`chunk_text()`** — splits article text into chunks no longer than 2,500 characters, preferring sentence boundaries (`". "`, `"! "`, `"? "`) over word boundaries, with a hard character-count split as a last resort
- **`synthesize_chunk()`** — calls `client.text_to_speech.convert()` for a single chunk, collecting the returned bytes iterator; wraps any ElevenLabs SDK exception in `TTSSynthesisError`
- **`get_audio_duration()`** — reads the MP3 duration in seconds from an in-memory `mutagen.mp3.MP3` object
- **`synthesize_article()`** — full pipeline: article lookup, cache-hit return (updating `last_played_at`), stale-file detection and recovery, 50,000-character cost guard, chunking, synthesis, MP3 assembly, duration measurement, disk write, and `audio_cache` row insertion
- **`sweep_expired_cache()`** — deletes `audio_cache` rows and their MP3 files where `last_played_at` is older than the configured TTL; accepts an explicit `ttl_days` override or falls back to `settings.audio_cache_ttl_days`
- **`get_cache_stats()`** — returns total file count, oldest, and newest `last_played_at` timestamps

**208 tests pass across Phases 1–7** (48 new tests covering `chunk_text` boundary algorithm — including sentence, space, hard-split, `! `, `? `, last-boundary selection, and empty-chunk filtering — `synthesize_chunk` bytes-joining and error wrapping, `get_audio_duration` mutagen delegation, `synthesize_article` cache-hit, stale-file recovery, cost guard, and `TTSSynthesisError` propagation, and `sweep_expired_cache` / `get_cache_stats` across multi-entry batches, settings-default TTL, single-entry stats, and post-sweep state).

---

## What is coming

### Phase 8 — Audio player

Wiring the synthesis layer into the browser UI. The synthesis back-end (`tts.py`) is fully implemented — Phase 8 exposes it through three new API routes (`POST /api/articles/{id}/audio`, `GET /api/articles/{id}/audio/status`, `GET /api/articles/{id}/audio/stream`) and adds an in-page audio player to the article detail view. Articles with Quanta's own narration URL surface that audio first, with local synthesis as a fallback.

### Phase 9 — Reading state and scheduler

The `POST /api/articles/{id}/state` endpoint persists reading status changes. `GET /api/queue` returns all queued articles. The `scheduler.py` background jobs run the feed refresh on a configurable interval and the cache sweep daily at 03:00.

### Phase 10 — Polish

Full-text search surfaced in the UI. Dark mode toggle with `localStorage` persistence. The remaining CLI flags (`--refresh-now`, `--sweep-cache`, `--no-browser`, `--verbose`). File logging via loguru to `data/voce.log`. Friendly empty states throughout the UI when sections are loading or have no articles.

---

## Out of scope

These features will not be added to Voce. The constraints are deliberate, not oversights.

**Multi-user or cloud sync.** Voce is a personal, private tool. Multi-tenancy would require authentication, session management, data isolation, and deployment infrastructure — none of which belongs in a single-user localhost application.

**Mobile app or browser extension.** The browser UI running at `localhost:8765` is already accessible from any browser on your machine. A native mobile app or extension would add significant complexity for no meaningful gain given the localhost-only design.

**Additional content sources.** Voce is built specifically around Quanta Magazine's editorial voice and content structure. Adding arbitrary RSS sources would break assumptions in the enrichment pipeline (LaTeX substitutions, topic extraction, attribution format) and dilute the focused listening experience.

**Audio export or sharing.** Synthesised audio is cached locally and served only to your browser. Exporting or sharing audio would create redistribution of content that Voce does not have a licence to redistribute. The cache expiry mechanism reinforces this: audio is ephemeral, not archival.

**Alternative TTS providers.** ElevenLabs is the chosen synthesis provider. Swapping it out is possible by replacing the internals of `tts.py`, but Voce does not abstract over providers or maintain multiple integrations. The quality of the narration is core to the experience — it is not a pluggable component.
