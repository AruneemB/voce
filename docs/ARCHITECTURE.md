# Architecture

Voce is a single-process, localhost-only web application. Its architecture is deliberately narrow: fetch science journalism from RSS, clean it for spoken narration, synthesise audio on demand, and serve everything through a browser UI — no cloud, no database server, no build pipeline.

---

## System overview

```text
Quanta Magazine RSS feeds
         │
         │  feedparser + httpx
         ▼
  ┌─────────────┐
  │  Ingestion  │  feeds.py
  │  (refresh)  │──────────────────────────────┐
  └─────────────┘                              │
         │ INSERT OR IGNORE                    │
         ▼                                     │
  ┌─────────────┐                              │
  │   SQLite    │  db.py / models.py           │
  │  voce.db    │◄─────────────────────────────┤
  └─────────────┘                              │
         │ SELECT                              │
         ▼                                     │
  ┌─────────────┐                              │
  │ Enrichment  │  article.py                  │
  │ (HTML→text) │  BeautifulSoup + LaTeX subs  │
  └─────────────┘                              │
         │ UPDATE body_text                    │
         ▼                                     │
  ┌─────────────┐                              │
  │  Synthesis  │  tts.py + cache.py           │
  │  (TTS/MP3)  │  ElevenLabs SDK              │
  └─────────────┘                              │
         │ MP3 file                            │
         ▼                                     │
  data/audio_cache/                            │
         │                                     │
         ▼                                     │
  ┌─────────────┐                              │
  │   FastAPI   │  api.py                      │
  │  HTTP layer │──────────────────────────────┘
  └─────────────┘
         │ HTTP/JSON + MP3 streaming
         ▼
  Browser (localhost:8765)
  index.html + app.js + Tailwind CDN + htmx
```

---

## Guiding principles

### Single-user, localhost-only

Voce is not a service — it runs on your machine and talks only to your browser. There is no authentication, no multi-tenancy, and no public interface. The `LocalhostOnlyMiddleware` enforces this with two independent checks (client IP and Host header), so the constraint is architectural, not advisory.

This design choice eliminates entire categories of security concerns (session management, rate limiting, data isolation, CORS) and keeps the system comprehensible. Every request comes from you.

### No ORM — SQL is the interface

All database access uses the Python standard library `sqlite3` module with parameterised queries. There is no SQLAlchemy, no Tortoise, no Peewee. The DDL is written once in `db.py` and is the single authoritative source for the schema.

This means the database layer is explicit and auditable. When you read `db.py` you see exactly what tables exist, what columns they have, and what indexes and triggers are in place. There is no magic.

### Synchronous database, asynchronous HTTP

The database is accessed synchronously via `sqlite3`. FastAPI routes are `async` but delegate all DB operations to a thread-pool executor via `asyncio.run_in_executor()`. This avoids the complexity of an async SQLite driver while retaining the concurrency benefits of an async HTTP framework.

### No build step for the frontend

The browser UI is a single HTML file that loads Tailwind CSS and htmx from CDN links. There is no npm, no webpack, no transpilation. A developer can edit `voce/static/app.js` and reload the browser to see the change immediately.

---

## Layer breakdown

### Ingestion — `feeds.py`

Polls four Quanta Magazine RSS feeds using `feedparser` and `httpx`. Each feed refresh:

1. Fetches the feed URL with exponential backoff retry (up to 3 attempts)
2. Parses entries into normalised article dicts
3. Upserts into the `articles` table (`INSERT OR IGNORE` — existing articles are not modified)
4. Creates a corresponding `reading_state` row for each new article

Article IDs are derived by SHA-256 hashing the canonical article URL, taking the first 16 hex characters. This makes IDs stable and reproducible without requiring a sequence.

### Enrichment — `article.py`

Converts raw HTML article bodies into clean prose suitable for text-to-speech:

1. **Removes noise** — strips `<script>`, `<style>`, `<aside>`, `<figure>`, `<iframe>`, `<noscript>`, and elements with CSS class names containing `share`, `newsletter`, `related`, `byline`, or `sidebar`
2. **Structures headings** — replaces heading tags with double-newline separators and trailing periods so they pause naturally in speech
3. **Handles special elements** — blockquotes become `Quote: ... End quote.`; ordered lists become `First, ... Second, ...`; unordered lists become comma-separated sequences ending with `and`
4. **Applies LaTeX substitutions** — converts common LaTeX expressions to spoken equivalents (e.g. `\frac{a}{b}` → `a over b`, `\sqrt{x}` → `the square root of x`, Greek letters spelled out)
5. **Normalises whitespace** — collapses runs of newlines and spaces

Every synthesised narration begins with an attribution preamble: `"From Quanta Magazine. {title}. By {author}. Published {date}."` This is prepended to the body text before synthesis.

### Persistence — `db.py`, `models.py`

A single SQLite file at `data/voce.db` holds all state. The schema is bootstrapped at startup via `bootstrap_schema()`, which runs the DDL script. The four tables — `articles`, `article_topics`, `reading_state`, `audio_cache` — model the complete article lifecycle from ingestion to playback.

An FTS5 virtual table (`fts_articles`) is maintained in sync with `articles` via three triggers (after insert, after update, after delete). Full-text search queries are routed through this index.

See [DATABASE.md](DATABASE.md) for complete schema documentation.

### Synthesis — `tts.py`, `cache.py`

When a user requests audio for an article, the synthesis pipeline:

1. Checks the `audio_cache` table — if an MP3 already exists for this article, `last_played_at` is updated and the cached path is returned immediately (no ElevenLabs call)
2. Builds the full narration text as `build_preamble(title, author, published_at) + "\n\n" + body_text`
3. Enforces the 50,000-character cost guard — articles exceeding this limit are refused with `ArticleTextMissingError` to prevent runaway ElevenLabs API spend
4. Chunks the text — the ElevenLabs API has a 2,500-character per-request limit; `chunk_text()` splits at sentence boundaries (`". "`, `"! "`, `"? "`) first, then at the last space within the limit, and finally performs a hard character-count split as a last resort — it never splits mid-word
5. Synthesises each chunk — calls `client.text_to_speech.convert()` with the configured voice and model IDs, collecting MP3 bytes; raises `TTSSynthesisError` on failure
6. Concatenates chunks — assembles a single MP3 file written to `data/audio_cache/{article_id}.mp3`
7. Reads the audio duration via `mutagen` and records the `audio_cache` row with the file path, voice ID, and duration in seconds

The `last_played_at` field in `audio_cache` is updated on every cache hit. `sweep_expired_cache()` in `cache.py` deletes files and rows where `last_played_at` is older than the configured TTL (default `settings.audio_cache_ttl_days`; the function also accepts an explicit `ttl_days` override).

### Scheduling — `scheduler.py`

An `APScheduler` `BackgroundScheduler` runs two jobs:

- **Feed refresh** — runs every N minutes (default 30, configurable via `FEED_REFRESH_MINUTES`)
- **Cache sweep** — runs daily at 3:00 AM

The scheduler starts during the FastAPI lifespan setup and shuts down cleanly when the server stops.

### API layer — `api.py`

A FastAPI application with `LocalhostOnlyMiddleware` applied globally. Routes are thin wrappers that:

1. Accept and validate query parameters via FastAPI's dependency injection
2. Execute parameterised SQL via a per-request connection (yielded by `get_conn()`, closed in a `finally` block)
3. Return Pydantic response models serialised to JSON

There is no business logic in the API layer. Ingestion, enrichment, and synthesis logic all live in their respective modules.

### Frontend — `voce/static/`

A single-page application built with vanilla JavaScript, htmx, and Tailwind CSS (both loaded from CDN — no build step). The layout has three columns filling the full viewport height:

- **Header** (`<header>`) — "Voce" wordmark, tagline "a reading companion for Quanta Magazine", a debounced search input (`#search-input`), and a Refresh button that posts to `POST /api/refresh`
- **Left sidebar** (`#sidebar`) — section list (`#section-list`) populated from `/api/sections`; status filter buttons (`#state-filters`: All, Unread, Queued, Listened) that filter the article list; topic dropdown (`#topic-filter`)
- **Article list** — scrollable centre panel (`#article-list`) with article cards, each showing title, author, date, a 200-character summary, and a colour-coded status badge. An `IntersectionObserver` watches `#load-more-sentinel` at the bottom and triggers the next page load automatically.
- **Article detail** (`#article-detail`) — full article view with title, byline, an "Open in Quanta ↗" link to the original, body text rendered as prose paragraphs, and a reserved `#audio-player-section` element for Phase 8.

Navigation uses `history.pushState` so the URL reflects the selected article (`#article/{id}`). On page load, `location.hash` is checked to resolve deep links. Toast notifications (errors, success confirmations) are appended to `#toast-container` and auto-dismissed after four seconds.

**XSS protection** — Every API-sourced string injected into `innerHTML` is passed through `escapeHtml()`, which encodes `&`, `<`, `>`, `"`, and `'` as HTML entities. Reading status strings used in CSS class names are validated against a `VALID_STATUSES` whitelist (`"unread"`, `"queued"`, `"listened"`) before interpolation; any unrecognised value falls back to `"unread"` rather than being used as-is. This ensures that malicious content in article titles, author names, or summaries cannot execute as HTML or JavaScript.

The audio player UI and reading status mutation buttons are not yet implemented — they are planned for later phases.

---

## Why these choices

| Decision | Rationale |
|----------|-----------|
| SQLite | Zero-dependency, embedded, ships with Python, FTS5 built-in. Single-user workload never stresses it. |
| No ORM | Keeps the database layer explicit and auditable. SQL is a better language for expressing SQL than a query builder. |
| ElevenLabs | High-quality neural narration is central to the Voce experience. |
| Vanilla JS + htmx | No build step, no framework churn, easy to read and modify by anyone comfortable with HTML. |
| Localhost-only | Privacy by design. No credentials, no auth, no exposure surface. The ethical stance against redistribution is enforced architecturally, not just by policy. |
| APScheduler | Simple background job scheduling without the overhead of a task queue or separate worker process. |
