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

**108 tests pass across Phases 1–5.**

---

## What is coming

### Phase 6 — Browser UI

The single-page frontend (`index.html`, `app.js`, `styles.css`) with a three-column layout: header with search and refresh, left sidebar with section list and topic filter, main panel with article cards and an infinite-scroll article list. Clicking an article card opens the detail view with full body text. Browser history is maintained via `pushState`.

### Phase 7 — TTS synthesis

The ElevenLabs synthesis layer (`tts.py`) splits article text into API-safe chunks, synthesises each chunk, and assembles the results into a single MP3 file. The cost guard refuses articles exceeding 50,000 characters. The cache layer (`cache.py`) provides the expiry sweep logic.

### Phase 8 — Audio player

Wiring the synthesis layer into the browser UI. The article detail view gains an audio player that triggers synthesis on demand, polls for synthesis status, and streams the completed MP3. Articles with Quanta's own narration URL surface that audio first, with local synthesis as a fallback.

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
