# Architecture

Voce is a single-process, localhost-only web application. Its architecture is deliberately narrow: fetch science journalism from RSS, clean it for spoken narration, synthesise audio on demand, and serve everything through a browser UI — no cloud, no database server, no build pipeline.

---

## System overview

```
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

1. Checks the `audio_cache` table — if an MP3 already exists for this article and voice, it is returned immediately
2. Measures article length — articles exceeding 50,000 characters are refused with a 413 response to prevent runaway ElevenLabs API spend
3. Chunks the text — the ElevenLabs API has a per-request character limit; `chunk_text()` splits at paragraph boundaries, then sentence boundaries, then word boundaries, never splitting mid-word
4. Synthesises each chunk — calls the ElevenLabs SDK with the configured voice and model IDs, collecting MP3 bytes
5. Concatenates chunks — assembles a single MP3 file in `data/audio_cache/{article_id}.mp3`
6. Records the cache entry — writes to `audio_cache` with the file path and duration

The `last_played_at` field in `audio_cache` is updated on every stream request. The cache sweep (`cache.py`) deletes files and rows where `last_played_at` is older than the configured TTL.

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

A single-page application built with vanilla JavaScript, htmx, and Tailwind CSS (both loaded from CDN). The layout has three columns:

- **Header** — wordmark, tagline, search input, refresh button
- **Left sidebar** — section list with unread counts, topic filter
- **Main panel** — article list (with infinite scroll via `IntersectionObserver`) or article detail view

Navigation uses `history.pushState` so the browser back button works correctly. Reading status buttons trigger `POST /api/articles/{id}/state` directly. The audio player appears in the detail view once synthesis completes.

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
