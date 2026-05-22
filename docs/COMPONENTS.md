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
ELEVENLABS_CHAR_LIMIT: int  # per-request character limit

def chunk_text(text: str, limit: int = ELEVENLABS_CHAR_LIMIT) -> list[str]: ...
def synthesize_chunk(text: str, voice_id: str, model_id: str) -> bytes: ...
def get_audio_duration(path: Path) -> int: ...
def synthesize_article(article_id: str, conn: sqlite3.Connection) -> Path: ...
def get_or_synthesize(article_id: str, conn: sqlite3.Connection) -> Path: ...
```

`chunk_text()` splits at paragraph boundaries first, then sentence boundaries, then space boundaries, and finally performs a hard character-count split as a last resort. It never splits inside a word.

`synthesize_article()` enforces the 50,000-character cost guard before beginning synthesis. It raises `TTSSynthesisError` (translated to HTTP 413) if the article is too long.

`get_or_synthesize()` checks `audio_cache` first. If a cached file exists with a matching `voice_id`, it returns the path without calling ElevenLabs. Otherwise it delegates to `synthesize_article()`.

---

## `cache.py` — Audio cache management

**Owns:** Sweeping expired audio files and reporting cache statistics.

```python
def sweep_expired_cache(conn: sqlite3.Connection) -> int: ...
def get_cache_stats(conn: sqlite3.Connection) -> dict: ...
```

`sweep_expired_cache()` deletes `audio_cache` rows where `last_played_at` is older than `settings.audio_cache_ttl_days`. It also deletes the corresponding MP3 files from disk. Returns the count of entries swept.

`get_cache_stats()` returns a dict with total cached articles, total disk usage in bytes, and the oldest and newest cache entries.

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
