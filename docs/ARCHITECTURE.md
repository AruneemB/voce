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
         │ HTTP/JSON                     POST /api/articles/{id}/audio
         │ GET /api/articles/{id}/audio/status  ◄──────────────────┐
         │ GET /api/articles/{id}/audio/stream  ────────────────────┐│
         ▼                                                          ││
  Browser (localhost:8765)                                          ││
  index.html + app.js + Tailwind CDN + htmx                        ││
         │                                                          ││
         │  renderAudioSection / pollAudioStatus                    ││
         │  (currentArticleId guard aborts stale polls)            ││
         └──────────────────────────────────────────────────────────┘│
                                                                      │
         _synthesis_in_progress (module-level set) ─────────────────┘
         fire-and-forget executor → synthesize_article() in thread
         (_run() opens own conn; releases in finally block)
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

The `httpx.Client` used for all feed requests is configured with `verify=certifi.where()` and `follow_redirects=True`. The certifi bundle (patched by `pip-system-certs` at runtime to use the OS-native trust store) ensures reliable TLS verification on all platforms including Windows. Redirect following is required because the Quanta Magazine feed URLs issue 301 redirects that httpx ≥ 0.20 does not follow by default.

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
4. Chunks the text — the ElevenLabs API has a 2,500-character per-request limit; `chunk_text()` splits at sentence boundaries (`". "`, `"! "`, `"? "`) first, then at the last space within the limit, and finally falls back to a hard character-count split when no whitespace exists within the limit (this last resort may split an oversized single token)
5. Synthesises each chunk — calls `client.text_to_speech.convert()` with the configured voice and model IDs, collecting MP3 bytes; raises `TTSSynthesisError` on failure
6. Concatenates chunks — assembles a single MP3 file written to `data/audio_cache/{article_id}.mp3`
7. Reads the audio duration via `mutagen` and records the `audio_cache` row with the file path, voice ID, and duration in seconds

The `last_played_at` field in `audio_cache` is updated on every cache hit. `sweep_expired_cache()` in `cache.py` deletes files and rows where `last_played_at` is older than the configured TTL (default `settings.audio_cache_ttl_days`; the function also accepts an explicit `ttl_days` override).

### Scheduling — `scheduler.py`

`build_scheduler(conn_factory)` creates an APScheduler `BackgroundScheduler` with two jobs:

- **Feed refresh** (`feed_refresh`) — interval trigger, fires every `FEED_REFRESH_MINUTES` minutes (default 30). Calls `refresh_all_feeds()` followed by `enrich_all_unenriched()` using a fresh connection opened via `conn_factory`. Both steps share a single `httpx.Client` (with certifi verification and redirect following) for the lifetime of the job.
- **Cache sweep** (`cache_sweep`) — cron trigger, fires daily at 03:00 UTC. Calls `sweep_expired_cache()` using a fresh connection.

Both jobs open and close their own connections independently to avoid cross-thread connection sharing. Errors are caught and logged so that one job failure does not affect the other.

The scheduler is started in the FastAPI `lifespan` context manager immediately after schema bootstrap. An additional daemon thread kicks off an immediate `refresh_all_feeds()` call followed by `enrich_all_unenriched()` at startup so that enrichment begins as early as possible, without waiting for the first interval tick. Because this runs in a daemon thread it does not block server startup; articles are enriched in the background while the server is already accepting requests. The lifespan teardown calls `scheduler.shutdown(wait=False)`.

### API layer — `api.py`

A FastAPI application with `LocalhostOnlyMiddleware` applied globally. Routes are thin wrappers that:

1. Accept and validate query parameters via FastAPI's dependency injection
2. Execute parameterised SQL via a per-request connection (yielded by `get_conn()`, closed in a `finally` block)
3. Return Pydantic response models serialised to JSON

There is no business logic in the API layer. Ingestion, enrichment, and synthesis logic all live in their respective modules.

The audio synthesis trigger (`POST /api/articles/{id}/audio`) dispatches `synthesize_article()` to a thread-pool executor with `asyncio.get_event_loop().run_in_executor()` and returns `202` immediately without awaiting the result (fire-and-forget). In-progress article IDs are tracked in the module-level set `_synthesis_in_progress`. This set is reset on server restart, which is acceptable for v1: any article whose synthesis was interrupted simply shows "pending" on the next status poll until the user triggers synthesis again.

Cached MP3 files are served from `settings.audio_cache_dir` via two routes: the `GET /audio/stream` endpoint (which also updates `last_played_at` and marks the article as listened), and a `StaticFiles` mount at `/audio` that exposes the directory directly for browsers that request byte ranges for seeking.

### API layer — full-text search

`GET /api/search?q=<query>` provides dedicated full-text search. The route attempts an FTS5 `MATCH` query via the `fts_articles` virtual table (which is maintained by triggers on `articles`). If FTS5 is unavailable (`sqlite3.OperationalError`), it falls back to a `LIKE`-based search on `title` and `body_text`. Results are ranked by FTS5 relevance in the primary path; the LIKE fallback orders by `published_at DESC`. The `LIKE` fallback builds its pattern string (`%q%`) in Python and passes it as a parameterised binding — `q` is never interpolated into the SQL string directly.

Both paths use `LEFT JOIN reading_state` with `COALESCE(status, 'unread')` so that articles not yet registered in `reading_state` are included in results with the correct default status, matching the behaviour of the main article-list endpoint.

### CLI layer — `__main__.py`

Three early-exit flags bypass uvicorn entirely:

- **`--refresh-now`** — opens a connection (wrapped in `try/finally`), calls `refresh_all_feeds()`, prints the per-section `(inserted, skipped)` counts, and exits with code 0. Useful for seeding the database on a new machine.
- **`--sweep-cache`** — opens a connection (wrapped in `try/finally`), calls `sweep_expired_cache()`, prints the count of deleted files, and exits with code 0. Useful for manual cache housekeeping.
- **`--no-browser`** — suppresses the `webbrowser.open()` call after server startup. Useful in headless or SSH environments.

On a normal startup, two loguru sinks are installed before uvicorn launches. `data/` is created with `Path("data").mkdir(parents=True, exist_ok=True)` first, because loguru does not create missing parent directories for file sinks:
- **stderr** — level from `--log-level`, concise `HH:mm:ss LEVEL module: message` format
- **`data/voce.log`** — level `DEBUG`, rotated at 10 MB, retained for 7 days

This ensures all startup events and debug output are captured to disk regardless of the terminal log level.

### Frontend — `voce/static/`

A single-page application built with vanilla JavaScript, htmx, and Tailwind CSS (both loaded from CDN — no build step). The layout has three columns filling the full viewport height:

- **Header** (`<header>`) — "Voce" wordmark, tagline "a reading companion for Quanta Magazine", a debounced search input (`#search-input`), a Refresh button that posts to `POST /api/refresh`, and a `🌙` dark mode toggle (`#theme-toggle`)
- **Left sidebar** (`#sidebar`) — section list (`#section-list`) populated from `/api/sections`; status filter buttons (`#state-filters`: All, Unread, Queued, Listened) that filter the article list; topic dropdown (`#topic-filter`)
- **Article list** — scrollable centre panel (`#article-list`) with article cards, each showing title, author, date, a 200-character summary, and a colour-coded status badge. An `IntersectionObserver` watches `#load-more-sentinel` at the bottom and triggers the next page load automatically.
- **Article detail** (`#article-detail`) — full article view with title, byline, an "Open in Quanta ↗" link to the original, body text rendered as prose paragraphs, and the `#audio-player-section` audio player slot.

**Dark mode** — Tailwind is configured with `darkMode: 'class'` via an inline config script placed before the CDN tag. The `toggleTheme()` function adds or removes the `dark` class on `<html>` and writes the preference to `localStorage`. On `DOMContentLoaded`, the preference is read back and applied before the first render. This means the user's chosen theme persists across page reloads and browser sessions with no flicker.

**`safeFetch` — unified error handling** — Every `fetch()` call is routed through `async function safeFetch(url, options)`. It throws `Error("HTTP {status}")` on non-OK responses, `await`s `resp.json()` inside the try block (so JSON parse failures are also caught and toasted), calls `showToast("Request failed: …", 'error')`, and re-throws. Callers either await and let the error propagate (for user-visible actions) or catch it silently (for background polling and optional status checks). This eliminates per-call `if (!resp.ok)` boilerplate and ensures all network errors — including malformed responses — reach the user as visible toast notifications.

Navigation uses `history.pushState` so the URL reflects the selected article (`#article/{id}`). On page load, `location.hash` is checked to resolve deep links. Toast notifications (errors, success confirmations) are appended to `#toast-container` and auto-dismissed after four seconds.

**XSS protection** — Every API-sourced string injected into `innerHTML` is passed through `escapeHtml()`, which encodes `&`, `<`, `>`, `"`, and `'` as HTML entities. Reading status strings used in CSS class names are validated against a `VALID_STATUSES` whitelist (`"unread"`, `"queued"`, `"listened"`) before interpolation; any unrecognised value falls back to `"unread"` rather than being used as-is. This ensures that malicious content in article titles, author names, or summaries cannot execute as HTML or JavaScript.

When an article is opened, `loadArticleDetail()` sets `currentArticleId` then fetches `/api/articles/{id}/audio/status` via `safeFetch` in a nested try/catch isolated from the article fetch. If the status request fails for any reason, `renderAudioSection()` is called with a default `{ cached: false, pending: false }` payload so the generate button always appears. Based on the response, `renderAudioSection()` shows an `<audio controls>` player (if audio is cached), a Quanta-narration player with a label (if `quanta_audio_url` is set), or a "Listen with Voce" button. The button carries no `onclick` attribute; a `click` listener is attached via `addEventListener` after the HTML is written. Clicking the button calls `requestAudio()`, which posts to `/api/articles/{id}/audio` via `safeFetch` and calls `pollAudioStatus()` if the response is `"pending"`. `pollAudioStatus()` checks `articleId === currentArticleId` at the start of each tick and aborts silently if the user has navigated away. Polling runs every 2 seconds for up to 120 seconds; on completion, `renderAudioSection()` swaps in the audio player.

The article detail view also renders three state toggle buttons — Queue, Mark Listened, and Mark Unread — via `data-state-action` attributes. Event listeners are attached with `addEventListener` after the HTML is written (no `onclick` attributes). Each button calls `setState(articleId, status)`, which POSTs via `safeFetch` to `POST /api/articles/{id}/state`. After the response resolves, `setState` checks `articleId === currentArticleId` before touching the DOM — if the user navigated away while the request was in flight, the response is silently discarded (matching the same stale-navigation guard used by `pollAudioStatus`). On success, `setState` updates the `#current-state` label with the new status and calls `loadSections()` to refresh the unread badge counts in the sidebar.

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
