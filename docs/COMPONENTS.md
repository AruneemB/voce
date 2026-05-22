# Components

Voce is structured as a single Python package (`voce/`) with eleven focused modules. Each module owns a well-defined slice of the system and exposes a small, explicit public interface.

---

## `config.py` — Settings and environment

**Owns:** Loading and exposing all runtime configuration.

```python
@dataclass
class Settings:
    elevenlabs_api_key: str
    elevenlabs_voice_id: str       # default: "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_model_id: str       # default: "eleven_turbo_v2_5"
    host: str                      # default: "127.0.0.1"
    port: int                      # default: 8765
    db_path: Path                  # default: data/voce.db
    audio_cache_dir: Path          # default: data/audio_cache
    audio_cache_ttl_days: int      # default: 30
    feed_refresh_minutes: int      # default: 30
    log_level: str                 # default: "INFO"

def load_settings() -> Settings: ...
settings: Settings  # module-level singleton
```

`load_settings()` raises `ValueError` immediately if `ELEVENLABS_API_KEY` is missing or empty. This fails fast at import time rather than at the point of first synthesis.

All other modules import `settings` from this module. No other module reads from `os.environ` directly.

---

## `db.py` — Database connection and schema

**Owns:** Opening SQLite connections and bootstrapping the schema on first run.

```python
def get_connection() -> sqlite3.Connection: ...
def bootstrap_schema(conn: sqlite3.Connection) -> None: ...
```

`get_connection()` opens a new connection each time it is called. It sets `row_factory = sqlite3.Row` (so columns are accessible by name), enables WAL journal mode, and turns on foreign key enforcement. Callers are responsible for closing the connection.

`bootstrap_schema()` runs the full DDL script via `executescript()`. All `CREATE TABLE`, `CREATE INDEX`, `CREATE VIRTUAL TABLE`, and `CREATE TRIGGER` statements use `IF NOT EXISTS`, so calling this on an existing database is safe and idempotent.

**Invariant:** No module other than `db.py` contains DDL. If you need to add a table, column, or index, it goes here.

---

## `models.py` — Database row dataclasses

**Owns:** Typed Python representations of database rows.

```python
@dataclass
class Article:
    id: str
    section: str
    title: str
    author: Optional[str]
    published_at: str
    url: str
    summary: Optional[str]
    body_html: str
    body_text: str
    quanta_audio_url: Optional[str]
    ingested_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Article": ...

@dataclass
class ReadingState:
    article_id: str
    status: str          # "unread" | "queued" | "listened"
    last_played_at: Optional[str]
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ReadingState": ...

@dataclass
class AudioCache:
    article_id: str
    file_path: str
    voice_id: str
    created_at: str
    last_played_at: str
    duration_sec: Optional[int]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "AudioCache": ...
```

Each `from_row()` classmethod filters `sqlite3.Row` keys against the dataclass fields, so queries that return extra columns (e.g. from JOINs) do not cause errors.

---

## `exceptions.py` — Custom exception hierarchy

**Owns:** All Voce-specific exception types.

```text
VoceError (base)
├── FeedFetchError(slug, url, cause)
├── ArticleFetchError(url, cause)
├── ArticleParseError(url, reason)
├── TTSSynthesisError(article_id, cause)
├── ArticleNotFoundError(article_id)
└── ArticleTextMissingError(article_id)
```

Domain exceptions are raised by ingestion, enrichment, and synthesis code and caught at the API boundary (where they are translated into appropriate HTTP status codes). They are never caught silently — if an exception is swallowed, a `logger.warning` or `logger.error` call accompanies it.

---

## `feeds.py` — RSS ingestion

**Owns:** Fetching, parsing, and persisting Quanta Magazine RSS feeds.

```python
QUANTA_FEEDS: dict[str, str]  # section slug → feed URL

def fetch_feed(slug: str, url: str, client: httpx.Client) -> feedparser.FeedParserDict: ...
def parse_entries(slug: str, parsed: feedparser.FeedParserDict) -> list[dict]: ...
def upsert_articles(entries: list[dict], conn: sqlite3.Connection) -> tuple[int, int]: ...
def refresh_all_feeds(conn: sqlite3.Connection) -> dict[str, tuple[int, int]]: ...
```

`fetch_feed()` retries up to three times with exponential back-off (1 s, 2 s, 4 s) on 5xx responses and timeouts. 4xx responses are not retried.

`parse_entries()` extracts the normalised article dict from each RSS entry. Article IDs are computed as `sha256(url)[:16]`. Publication timestamps default to the current UTC time if the RSS entry lacks a `published` field. The audio enclosure URL (Quanta's own narration, when present) is extracted from the `enclosures` list.

`upsert_articles()` uses `INSERT OR IGNORE` — if an article's URL is already in the database, it is skipped. A corresponding `reading_state` row (status `"unread"`) is created alongside each new article.

`refresh_all_feeds()` orchestrates the full pipeline and returns per-section `(inserted, skipped)` counts. Failures in one section do not abort the remaining sections.

---

## `article.py` — HTML enrichment and text cleaning

**Owns:** Converting raw HTML article bodies into prose ready for text-to-speech.

```python
def apply_latex_substitutions(text: str) -> str: ...
def count_words(text: str) -> int: ...
def clean_html_for_tts(html: str) -> str: ...
def build_preamble(title: str, author: str | None, published_at: str) -> str: ...
def fetch_article_html(url: str, client: httpx.Client) -> str: ...
def enrich_article(article_id, url, body_html, conn, client) -> bool: ...
def enrich_all_unenriched(conn, client) -> tuple[int, int]: ...
```

`clean_html_for_tts()` runs a ten-step pipeline: remove noise elements, replace `<br>` with newlines, convert headings, handle blockquotes, convert lists to natural language, strip remaining tags, apply LaTeX substitutions, normalise whitespace.

`apply_latex_substitutions()` applies a sequence of regex replacements in order. Structural conversions (fractions, roots, superscripts) run first; Greek letter and symbol expansions run second; catch-all strippers for remaining LaTeX syntax run last.

`build_preamble()` returns `"From Quanta Magazine. {title}. By {author}. Published {date}."`. This attribution preamble is prepended to every narration.

`enrich_article()` checks whether `body_html` is already populated. If not, it fetches the article page directly before cleaning. Either way, the cleaned text and preamble are written back to `articles.body_text`.

---

## `tts.py` — ElevenLabs synthesis and MP3 assembly

**Owns:** Splitting text into API-safe chunks, calling ElevenLabs, and assembling the final MP3.

```python
ELEVENLABS_CHAR_LIMIT: int = 2500  # per-request character limit

def chunk_text(text: str, limit: int = ELEVENLABS_CHAR_LIMIT) -> list[str]: ...
def synthesize_chunk(text: str, client: ElevenLabs) -> bytes: ...
def get_audio_duration(mp3_bytes: bytes) -> float: ...
def synthesize_article(article_id: str, conn: sqlite3.Connection) -> Path: ...
```

`chunk_text()` splits at sentence boundaries (`". "`, `"! "`, `"? "`) first, then at the last space within the limit, and falls back to a hard character-count split only when no whitespace exists within the limit. This last resort may split an oversized single token. Empty strings are filtered from the result.

`synthesize_chunk()` calls `client.text_to_speech.convert()` with the configured voice and model IDs. It collects the returned bytes iterator with `b"".join(...)`. On any exception from ElevenLabs it raises `TTSSynthesisError(article_id="unknown", cause=exc)`.

`get_audio_duration()` reads the length from an in-memory `mutagen.mp3.MP3` object and returns it as a float (seconds).

`synthesize_article()` is the full pipeline:
1. Queries the article by ID; raises `ArticleNotFoundError` if missing, `ArticleTextMissingError` if `body_text` is empty.
2. Checks `audio_cache` — if a cached entry exists **and the MP3 file is present on disk**, updates `last_played_at` and returns the cached path immediately (no ElevenLabs call). If the row exists but the file is missing, the stale row is deleted and synthesis proceeds normally.
3. Builds the full narration text: `build_preamble(title, author, published_at) + "\n\n" + body_text`.
4. Enforces the 50,000-character cost guard; raises `ArticleTextMissingError` if exceeded.
5. Chunks, synthesises, concatenates, writes the MP3 to `settings.audio_cache_dir/{article_id}.mp3`, inserts the `audio_cache` row, and returns the path.

---

## `cache.py` — Audio cache management

**Owns:** Sweeping expired audio files and reporting cache statistics.

```python
def sweep_expired_cache(conn: sqlite3.Connection, ttl_days: int | None = None) -> int: ...
def get_cache_stats(conn: sqlite3.Connection) -> dict: ...
```

`sweep_expired_cache()` deletes `audio_cache` rows where `last_played_at` is older than `ttl_days` ago. `ttl_days` defaults to `settings.audio_cache_ttl_days` when not provided; it is coerced to `int` and must be non-negative (raises `ValueError` otherwise). RFC3339 timestamps stored in `last_played_at` are normalised via SQLite's `datetime()` before comparison to avoid lexicographic ordering errors. The corresponding MP3 file is deleted from disk (silently skipped if already missing) before the row is removed. Returns the count of entries swept.

`get_cache_stats()` returns a dict with three keys:

```python
{
    "total_files": int,           # number of rows in audio_cache
    "oldest_played_at": str | None,  # earliest last_played_at timestamp
    "newest_played_at": str | None,  # most recent last_played_at timestamp
}
```

---

## `scheduler.py` — Background job scheduling

**Owns:** Configuring and managing the APScheduler background scheduler.

```python
def start_scheduler() -> BackgroundScheduler: ...
def stop_scheduler(scheduler: BackgroundScheduler) -> None: ...
```

`start_scheduler()` creates an `APScheduler` `BackgroundScheduler` with two jobs:

- Feed refresh: every `settings.feed_refresh_minutes` minutes, starting immediately
- Cache sweep: daily at 03:00 local time

The scheduler is started as part of the FastAPI lifespan and shut down cleanly on server exit.

---

## `api.py` — FastAPI application and routes

**Owns:** The HTTP layer — middleware, route definitions, and response models.

```python
class LocalhostOnlyMiddleware(BaseHTTPMiddleware): ...

class SectionOut(BaseModel): ...
class ArticleSummaryOut(BaseModel): ...
class ArticleDetailOut(ArticleSummaryOut): ...
class PaginatedArticles(BaseModel): ...
class TopicOut(BaseModel): ...

def create_app() -> FastAPI: ...
app: FastAPI  # module-level instance
```

`create_app()` wires up `LocalhostOnlyMiddleware`, mounts the static file directory, and sets the lifespan context (which bootstraps the schema on startup).

All routes are thin: validate inputs, run a parameterised query via the `ConnDep` dependency, return a Pydantic model. No business logic lives in routes.

The `ConnDep` dependency (`Annotated[sqlite3.Connection, Depends(get_conn)]`) opens a connection at the start of each request and closes it in a `finally` block, regardless of whether the request succeeded.

---

## `__main__.py` — CLI entry point

**Owns:** Argument parsing and launching the uvicorn server.

```python
def main() -> None: ...
```

Invoked via `python -m voce` or the `voce` console script defined in `pyproject.toml`. Accepts `--host`, `--port`, and `--log-level` flags (with additional flags planned for later phases: `--refresh-now`, `--sweep-cache`, `--no-browser`, `--verbose`). Starts uvicorn pointing at `voce.api:app`.

---

## `voce/static/` — Browser frontend

**Owns:** The complete single-page browsing UI served at `GET /`.

The three files are served as static assets by FastAPI's `StaticFiles` mount at `/static`. The root route (`GET /`) returns `index.html` directly via `FileResponse`. No build tool, bundler, or transpiler is involved — edits to these files are reflected immediately on browser reload.

---

### `index.html`

The application shell. Declares the three-column viewport-filling layout, loads Tailwind CSS and htmx from CDN, and links `styles.css` and `app.js`. All element IDs referenced by `app.js` are declared here:

| ID | Element | Role |
|----|---------|------|
| `#sidebar` | `<aside>` | Left sidebar wrapper (sections, status filters, topic dropdown) |
| `#section-list` | `<ul>` | Section buttons, populated by `loadSections()` |
| `#state-filters` | `<div>` | All / Unread / Queued / Listened filter buttons |
| `#topic-filter` | `<select>` | Topic filter dropdown |
| `#article-list` | `<div>` | Article card container, populated by `loadArticles()` |
| `#load-more-sentinel` | `<div>` | `IntersectionObserver` target for infinite scroll |
| `#article-detail` | `<article>` | Article detail view, populated by `loadArticleDetail()` |
| `#audio-player-section` | `<div>` | Reserved slot for the Phase 8 audio player |
| `#toast-container` | `<div>` | Fixed-position notification stack |
| `#search-input` | `<input type="search">` | Debounced full-text search |

CDN script tags use the exact URLs and integrity attributes required by the spec:

```html
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://unpkg.com/htmx.org@1.9.10"
        integrity="sha384-D1Kt99CQMDuVetoL1lrYwg5t+9QdHe7NLX/SoJYkXDFfX37iInKRy5ViYgSibmK"
        crossorigin="anonymous"></script>
```

---

### `app.js`

All application behaviour. Module-level state and public functions:

```javascript
// Mutable filter state — reset between navigation actions
let currentSection = null;   // active section slug, or null (all sections)
let currentTopic   = null;   // active topic slug, or null; driven by #topic-filter
let currentStatus  = null;   // "unread" | "queued" | "listened" | null
let currentOffset  = 0;      // pagination cursor; reset to 0 on filter change
const PAGE_SIZE = 30;        // results per page, matches API default

// Pagination guards — prevent duplicate in-flight fetches and over-fetching
let isLoadingArticles = false;  // true while a loadArticles fetch is in flight
let hasMoreArticles   = true;   // false once the API returns fewer than PAGE_SIZE items

// Security
const VALID_STATUSES = new Set(['unread', 'queued', 'listened']);
```

| Function | Signature | Description |
|----------|-----------|-------------|
| `escapeHtml` | `(value) → string` | Encodes `&`, `<`, `>`, `"`, `'` as HTML entities. Applied to every API-sourced string before injection into `innerHTML`. |
| `loadSections` | `async () → void` | Fetches `/api/sections`, renders `<li><button data-section="{slug}">` items with unread badge counts into `#section-list`. Section click sets `currentSection` and calls `loadArticles(true)`. |
| `loadArticles` | `async (reset = true) → void` | Guarded by `isLoadingArticles` (drops concurrent calls) and `hasMoreArticles` (stops requesting once the last page is received). Fetches `/api/articles` with current filter params. `reset = true` clears `#article-list`, resets `currentOffset`, and restores `hasMoreArticles`. Appends article cards and advances `currentOffset` by the actual item count returned. |
| `loadArticleDetail` | `async (articleId) → void` | Fetches `/api/articles/{id}`, renders title, byline, "Open in Quanta ↗" link, `#audio-player-section` slot, and prose body (`body_text` split on `\n\n`, each paragraph HTML-escaped) into `#article-detail`. Calls `history.pushState`. |
| `showToast` | `(message, type) → void` | Creates a coloured `<div>` (red for `"error"`, green for `"success"`, blue for `"info"`) in `#toast-container`. Auto-removes after 4000 ms via `setTimeout`. |
| `triggerRefresh` | `async () → void` | Posts to `/api/refresh`, shows a success or error toast, then reloads sections and articles. |

All article fields injected via `innerHTML` (`title`, `author`, `summary`, `body_text`, `display_name`) are passed through `escapeHtml()`. Status values used in CSS class names are validated against `VALID_STATUSES` before interpolation; any unrecognised status falls back to `"unread"`.

The `DOMContentLoaded` handler wires together:

1. `loadSections()` — initial section list
2. `loadArticles(true)` — initial article list
3. `IntersectionObserver` on `#load-more-sentinel` → `loadArticles(false)` when sentinel enters viewport (guard prevents duplicate loads)
4. `#state-filters` click delegation → update `currentStatus`, reload articles
5. `#topic-filter` change event → update `currentTopic` (empty string coerced to `null` for "All topics"), reset offset, reload articles
6. `#search-input` input event → 300 ms debounce → fetch `/api/search?q=` (falls back to `/api/articles?q=` on 404) → render results
7. `location.hash` check → if matches `#article/{id}`, call `loadArticleDetail` immediately

---

### `styles.css`

Custom component styles that extend Tailwind's utility classes. These classes are used in the JavaScript-generated markup and cannot be expressed as Tailwind utilities alone.

| Selector | Purpose |
|----------|---------|
| `.prose` | Serif body typography at `70ch` max-width, `1.7` line-height, `Georgia` font family |
| `.prose p` | `1.2em` bottom margin between body paragraphs |
| `.article-card` | Pointer cursor, padded border-bottom rows with `0.1s` hover transition |
| `.article-card:hover`, `.article-card.active` | `#f0f9ff` background highlight |
| `.status-badge` | Pill shape — rounded, uppercase, small text — shared by all three status colours |
| `.status-unread` | Blue pill (`#dbeafe` / `#1d4ed8`) |
| `.status-queued` | Yellow pill (`#fef9c3` / `#854d0e`) |
| `.status-listened` | Green pill (`#dcfce7` / `#166534`) |
| `#toast-container` | `position: fixed`, top-right corner, `z-index: 9999`, flex column with gap |
| `.quanta-link` | Bold, underlined, blue (`#2563eb`) "Open in Quanta ↗" anchor |
