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
_IDENT_RE: re.Pattern              # ^[A-Za-z_][A-Za-z0-9_]*$ — valid SQL identifiers
_ALLOWED_COL_TYPES: frozenset[str] # {"INTEGER", "TEXT", "REAL", "BLOB", "NUMERIC"}

def _safe_ident(name: str) -> str: ...             # validates + double-quotes an identifier
def _add_column_if_missing(conn, table, column, col_type) -> None: ...
def get_connection() -> sqlite3.Connection: ...
def bootstrap_schema(conn: sqlite3.Connection) -> None: ...
```

`get_connection()` opens a new connection each time it is called. It sets `row_factory = sqlite3.Row` (so columns are accessible by name), enables WAL journal mode, and turns on foreign key enforcement. Callers are responsible for closing the connection.

`bootstrap_schema()` runs the full DDL script via `executescript()`. All `CREATE TABLE`, `CREATE INDEX`, `CREATE VIRTUAL TABLE`, and `CREATE TRIGGER` statements use `IF NOT EXISTS`, so calling this on an existing database is safe and idempotent. After running the DDL, it calls `_add_column_if_missing()` for any column that was added to an existing table after the initial schema was deployed.

`_safe_ident()` validates that an identifier matches `^[A-Za-z_][A-Za-z0-9_]*$` and raises `ValueError` otherwise, then wraps the name in double-quotes. This prevents SQL injection when identifier names are interpolated into `ALTER TABLE` or `PRAGMA` statements.

`_add_column_if_missing()` calls `_safe_ident()` on both `table` and `column`, validates `col_type` against `_ALLOWED_COL_TYPES`, then inspects `PRAGMA table_info("{table}")` and issues `ALTER TABLE … ADD COLUMN` only when the named column is absent. This is necessary because SQLite does not support `ALTER TABLE … ADD COLUMN IF NOT EXISTS`. The helper is idempotent: calling it on a database that already has the column is a no-op.

**Invariant:** No module other than `db.py` contains DDL. If you need to add a table, column, or index, it goes here. New columns on existing tables require a `_add_column_if_missing()` call in `bootstrap_schema`, not a separate migration script.

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

The `httpx.Client` used by `refresh_all_feeds()` is constructed with `verify=certifi.where()` and `follow_redirects=True`. `certifi` is patched at runtime by `pip-system-certs` to return the OS-native certificate bundle, ensuring reliable TLS on Windows. `follow_redirects=True` is required because the Quanta Magazine feed URLs issue 301 redirects that httpx ≥ 0.20 does not follow by default.

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

When iterating all remaining tags to filter by CSS class, the function guards against nodes whose `attrs` attribute is `None` (a real case with lxml when parsing complex pages containing CDATA sections or processing instructions). Such nodes are skipped rather than triggering an `AttributeError` on `tag.get("class")`.

`apply_latex_substitutions()` applies a sequence of regex replacements in order. Structural conversions (fractions, roots, superscripts) run first; Greek letter and symbol expansions run second; catch-all strippers for remaining LaTeX syntax run last.

`build_preamble()` returns `"From Quanta Magazine. {title}. By {author}. Published {date}."`. This attribution preamble is prepended to every narration.

`enrich_article()` checks whether `body_html` is already populated. If not, it fetches the article page directly before cleaning. Either way, the cleaned text and preamble are written back to `articles.body_text`.

`enrich_all_unenriched()` is the batch entry point: it selects all articles where `body_text` is empty or null, calls `enrich_article()` for each, commits once at the end, and returns `(success_count, failure_count)`. It is called automatically after every feed refresh — from the startup daemon thread, the scheduled `_refresh_job`, and the `POST /api/refresh` endpoint.

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

**Owns:** Configuring the APScheduler background scheduler with feed refresh and cache sweep jobs.

```python
def _refresh_job(conn_factory: Callable[[], sqlite3.Connection]) -> None: ...
def _sweep_job(conn_factory: Callable[[], sqlite3.Connection]) -> None: ...
def build_scheduler(conn_factory: Callable[[], sqlite3.Connection]) -> BackgroundScheduler: ...
```

`build_scheduler()` creates and configures a `BackgroundScheduler` with `timezone="UTC"` but does not start it — the caller is responsible for calling `.start()` and `.shutdown()`. It registers two jobs:

- **`feed_refresh`** — interval trigger, fires every `settings.feed_refresh_minutes` minutes; calls `_refresh_job(conn_factory)`, which opens a fresh connection, calls `refresh_all_feeds()`, logs the per-section counts, and closes the connection in a `finally` block.
- **`cache_sweep`** — cron trigger, fires daily at 03:00 UTC; calls `_sweep_job(conn_factory)`, which opens a fresh connection, calls `sweep_expired_cache()`, logs the count of deleted files, and closes the connection.

Both private job functions guard against connection errors by initialising `conn = None` before the `try` block. The `conn_factory()` call is inside `try` so that a factory failure is caught and logged rather than crashing the scheduler thread. The `finally` block uses `if conn is not None: conn.close()` to ensure the connection is only closed when it was actually opened. Each job opens its own connection (via `conn_factory`) rather than sharing a connection across threads.

`build_scheduler()` is called in the FastAPI `lifespan` context, which starts the scheduler on app startup and calls `scheduler.shutdown(wait=False)` on teardown.

---

## `api.py` — FastAPI application and routes

**Owns:** The HTTP layer — middleware, route definitions, and response models.

```python
_synthesis_in_progress: set[str]  # module-level; tracks in-flight article IDs

class LocalhostOnlyMiddleware(BaseHTTPMiddleware): ...

class SectionOut(BaseModel): ...
class ArticleSummaryOut(BaseModel): ...
class ArticleDetailOut(ArticleSummaryOut): ...
class PaginatedArticles(BaseModel): ...
class TopicOut(BaseModel): ...
class AudioStatusOut(BaseModel): ...    # cached, url, duration_sec, pending
class StateUpdate(BaseModel): ...       # status: Literal["unread","queued","listened"]
class ReadingStateOut(BaseModel): ...   # article_id, status, last_played_at, updated_at

def create_app() -> FastAPI: ...
app: FastAPI  # module-level instance
```

`create_app()` wires up `LocalhostOnlyMiddleware`, mounts the `/static` file directory, ensures `settings.audio_cache_dir` exists, mounts the audio cache directory under `/audio`, and sets the lifespan context.

The `lifespan` context manager:
1. Opens a connection, runs `bootstrap_schema()`, and closes it.
2. Calls `build_scheduler(get_connection)` and starts the returned scheduler.
3. Launches a daemon thread that runs a `_refresh_once()` helper, which opens a connection, calls `refresh_all_feeds()`, and closes the connection in a `finally` block — ensuring the startup connection is always released.
4. On teardown (after `yield`), calls `scheduler.shutdown(wait=False)`.

All routes are thin: validate inputs, run a parameterised query via the `ConnDep` dependency, return a Pydantic model. No business logic lives in routes.

The `ConnDep` dependency (`Annotated[sqlite3.Connection, Depends(get_conn)]`) opens a connection at the start of each request and closes it in a `finally` block, regardless of whether the request succeeded.

**State, queue, and search routes:**

| Route | What it does |
|-------|-------------|
| `POST /api/articles/{id}/state` | Validates the article exists (404 if not), then UPSERTs `reading_state` with transition rules for `last_played_at`. Returns `ReadingStateOut`. |
| `GET /api/queue` | Queries articles joined to `reading_state WHERE status='queued'` ordered by `updated_at ASC`. Returns `list[ArticleSummaryOut]`. |
| `GET /api/search` | Attempts an FTS5 `MATCH` query against the `fts_articles` virtual table; catches `sqlite3.OperationalError` and falls back to a parameterised `LIKE` query on `title` and `body_text`. Returns `list[ArticleSummaryOut]`. |

**Audio routes:**

| Route | What it does |
|-------|-------------|
| `POST /api/articles/{id}/audio` | Checks `_synthesis_in_progress` and `audio_cache` (verifying the MP3 file exists on disk); dispatches `synthesize_article()` to a thread-pool executor (fire-and-forget); returns `202` immediately |
| `GET /api/articles/{id}/audio/status` | Returns `AudioStatusOut` — cache state (verified against disk), stream URL, duration, and pending flag — without triggering synthesis |
| `GET /api/articles/{id}/audio/stream` | Verifies the MP3 file exists before serving; updates `audio_cache.last_played_at` and sets `reading_state.status = 'listened'` |

All three audio routes perform a file-existence check after reading from `audio_cache`. When the row exists but the MP3 file has been deleted, the stale row is removed and the endpoint behaves as if no audio is cached (falling through to the uncached path or returning `404`). The background `_run()` thread opens its own database connection and releases it in a `finally` block to avoid cross-thread connection sharing.

`_synthesis_in_progress` is a plain Python `set[str]` at module level. It is guarded by the GIL, which is sufficient for a single-process server. The set resets on server restart; any interrupted synthesis is simply re-triggered by the user.

---

## `__main__.py` — CLI entry point

**Owns:** Argument parsing and launching the uvicorn server.

```python
def main() -> None: ...
```

Invoked via `python -m voce` or the `voce` console script defined in `pyproject.toml`.

**Flags:**

| Flag | Type | Description |
|------|------|-------------|
| `--host` | string | Bind address (default: `settings.host`) |
| `--port` | integer | Port number (default: `settings.port`) |
| `--log-level` | string | Uvicorn/loguru log level (default: `settings.log_level`) |
| `--refresh-now` | boolean | Fetch all feeds, print per-section counts, and exit 0 — does not start uvicorn |
| `--sweep-cache` | boolean | Delete expired audio cache entries, print count, and exit 0 — does not start uvicorn |
| `--no-browser` | boolean | Do not open a browser window after starting the server |

**Log routing:** After early-exit flags are handled, `main()` calls `Path("data").mkdir(parents=True, exist_ok=True)` to guarantee the log directory exists (loguru does not create missing parent directories for file sinks), then removes the default loguru handler, adds a stderr sink (level from `--log-level`, concise timestamp/level/module format), and adds a rotating file sink writing to `data/voce.log` (rotation at 10 MB, retention for 7 days, level `DEBUG`). This runs before uvicorn starts so all startup events are captured.

**Early-exit flow:** `--refresh-now` and `--sweep-cache` open a connection via `get_connection()` and execute their operation inside a `try/finally` block so the connection is always closed even if the operation raises — `raise SystemExit(0)` is inside the `try` so the `finally` still runs before the process exits. They do not configure loguru or launch uvicorn.

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
| `#audio-player-section` | `<div>` | Reserved slot for the audio player |
| `#toast-container` | `<div>` | Fixed-position notification stack |
| `#search-input` | `<input type="search">` | Debounced full-text search |
| `#theme-toggle` | `<button>` | Dark mode toggle (`🌙`); calls `toggleTheme()` via `onclick` |

**Dark mode configuration:** A `<script>tailwind.config = { darkMode: 'class' }</script>` tag is placed immediately before the Tailwind CDN tag. This instructs Tailwind to activate dark-mode variants when the `dark` class is present on `<html>` rather than responding to `prefers-color-scheme`.

CDN script tags:

```html
<script>tailwind.config = { darkMode: 'class' }</script>
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
let currentSection   = null;   // active section slug, or null (all sections)
let currentTopic     = null;   // active topic slug, or null; driven by #topic-filter
let currentStatus    = null;   // "unread" | "queued" | "listened" | null
let currentOffset    = 0;      // pagination cursor; reset to 0 on filter change
let currentArticleId = null;   // ID of the article currently displayed in the detail pane
const PAGE_SIZE = 30;          // results per page, matches API default

// Pagination guards — prevent duplicate in-flight fetches and over-fetching
let isLoadingArticles = false;  // true while a loadArticles fetch is in flight
let hasMoreArticles   = true;   // false once the API returns fewer than PAGE_SIZE items

// Security
const VALID_STATUSES = new Set(['unread', 'queued', 'listened']);
```

| Function | Signature | Description |
|----------|-----------|-------------|
| `safeFetch` | `async (url, options) → any` | Wraps `fetch()`: throws `Error("HTTP {status}")` on non-OK responses, `await`s `resp.json()` inside the try block so JSON parse errors are also caught and toasted, shows an error toast via `showToast`, then re-throws. Returns the parsed JSON body on success. Every API call in the file goes through this wrapper. |
| `escapeHtml` | `(value) → string` | Encodes `&`, `<`, `>`, `"`, `'` as HTML entities. Applied to every API-sourced string before injection into `innerHTML`. |
| `toggleTheme` | `() → void` | Toggles the `dark` class on `document.documentElement` and persists the preference to `localStorage` under the key `theme`. |
| `loadSections` | `async () → void` | Fetches `/api/sections` via `safeFetch`, renders `<li><button data-section="{slug}">` items with unread badge counts into `#section-list`. Section click sets `currentSection` and calls `loadArticles(true)`. |
| `loadArticles` | `async (reset = true) → void` | Guarded by `isLoadingArticles` (drops concurrent calls) and `hasMoreArticles` (stops requesting once the last page is received). Fetches `/api/articles` via `safeFetch` with current filter params. `reset = true` clears `#article-list`, resets `currentOffset`, and restores `hasMoreArticles`. Appends article cards and advances `currentOffset` by the actual item count returned. |
| `loadArticleDetail` | `async (articleId) → void` | Sets `currentArticleId = articleId` immediately (before any awaits) so stale audio polls can detect navigation. Fetches `/api/articles/{id}` via `safeFetch`, renders the detail pane, then fetches audio status in a nested try/catch that is isolated from the article fetch. If the status fetch fails for any reason, `renderAudioSection` is called with `{ cached: false, pending: false }` so the generate button is always shown. Calls `history.pushState`. |
| `renderAudioSection` | `(articleId, statusData, article) → void` | Dispatches to `buildAudioPlayer` (if cached), a Quanta-narration player with label (if `article.quanta_audio_url` is set), or `buildGenerateButton`. After inserting the generate button via `innerHTML`, attaches the `click` listener via `addEventListener` — no `onclick` attribute is used. |
| `buildAudioPlayer` | `(src, durationSec) → string` | Returns `<audio controls src="…">` HTML with an optional `"M:SS"` duration label. All values are passed through `escapeHtml`. |
| `buildGenerateButton` | `(pending) → string` | Returns an animated spinner paragraph when `pending` is true, or a `<button class="btn-generate">Listen with Voce</button>` otherwise. The button carries no `onclick` attribute; callers attach the listener via `addEventListener` after inserting the HTML. |
| `formatDuration` | `(seconds) → string` | Converts a duration in seconds to `"M:SS"` display format. |
| `requestAudio` | `async (articleId) → void` | Posts to `/api/articles/{id}/audio` via `safeFetch`. If the response is `"ready"`, re-fetches status and calls `renderAudioSection`. If `"pending"`, calls `pollAudioStatus(articleId, 0)`. On error, restores the generate button via `innerHTML` + `addEventListener`. |
| `pollAudioStatus` | `(articleId, attempt) → void` | Retries every 2 seconds. Aborts immediately (without rendering) if `articleId !== currentArticleId`, preventing stale-poll results from overwriting the detail pane when the user has navigated to a different article. After 60 attempts (120 seconds), shows an error toast and restores the generate button. |
| `showToast` | `(message, type) → void` | Creates a coloured `<div>` (red for `"error"`, green for `"success"`, blue for `"info"`) in `#toast-container`. Auto-removes after 4000 ms via `setTimeout`. |
| `triggerRefresh` | `async () → void` | Shows a "Refreshing feeds…" info toast immediately, then POSTs to `/api/refresh` via `safeFetch`. On success, computes the total new-article count from the response and shows a "Refresh complete. N new articles." toast, then reloads sections and articles. Errors are silently swallowed (toast already shown by `safeFetch`). |
| `setState` | `async (articleId, status) → void` | POSTs `{status}` to `/api/articles/{id}/state` via `safeFetch`. After the response resolves, checks `articleId === currentArticleId` before updating the DOM — if the user navigated to a different article while the request was in flight, the response is silently discarded. On success, updates `#current-state` text and calls `loadSections()` to refresh unread badge counts. Listeners are attached via `addEventListener` on `[data-state-action]` buttons — no `onclick` attribute is used. |

All article fields injected via `innerHTML` (`title`, `author`, `summary`, `body_text`, `display_name`) are passed through `escapeHtml()`. Status values used in CSS class names are validated against `VALID_STATUSES` before interpolation; any unrecognised status falls back to `"unread"`. The generate button never carries an `onclick` attribute; event listeners are always attached via `addEventListener` after the HTML is written, preventing any risk of script injection through article ID values.

The `DOMContentLoaded` handler wires together:

1. Dark mode restoration — reads `localStorage.getItem('theme')` and adds `dark` to `<html>` if set to `'dark'`
2. `loadSections()` — initial section list
3. `loadArticles(true)` — initial article list
4. `IntersectionObserver` on `#load-more-sentinel` → `loadArticles(false)` when sentinel enters viewport (guard prevents duplicate loads)
5. `#state-filters` click delegation → update `currentStatus`, reload articles
6. `#topic-filter` change event → update `currentTopic` (empty string coerced to `null` for "All topics"), reset offset, reload articles
7. `#search-input` input event → 300 ms debounce → `safeFetch('/api/search?q=...')` → render results as article cards (each card has both `click` and `keydown` Enter/Space handlers for keyboard accessibility)
8. `location.hash` check → if matches `#article/{id}`, call `loadArticleDetail` immediately

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
| `.btn-generate` | Blue (`#2563eb`) pill button for the "Listen with Voce" CTA; hover darkens to `#1d4ed8` |
| `.btn-generate:focus-visible` | `2px solid #1d4ed8` outline with `2px` offset — keyboard-navigation focus ring |
