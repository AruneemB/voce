# Development

This document covers setting up a development environment, running the test suite, and the conventions that apply throughout the codebase.

---

## Dev environment setup

```bash
git clone https://github.com/AruneemB/voce.git
cd voce
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -e .
cp .env.example .env
# Set ELEVENLABS_API_KEY in .env
```

The project uses `pyproject.toml` for all configuration (`[tool.pytest.ini_options]`, etc.). There is no `pytest.ini`, `setup.cfg`, or `setup.py`.

---

## Running tests

```bash
pytest
```

The test suite is in `tests/`. Tests are organised by module:

| File | Covers |
|------|--------|
| `test_skeleton.py` | Package imports and entry point exist |
| `test_config.py` | Settings loading, API key validation, defaults |
| `test_db.py` | Schema bootstrap, FTS5 table, triggers, FK cascades |
| `test_feeds.py` | RSS parsing, upsert logic, retry behaviour; httpx.Client created with certifi verification and redirect following |
| `test_article.py` | HTML cleaning, LaTeX substitutions, preamble format; regression for `None`-attrs nodes produced by lxml |
| `test_api.py` | FastAPI routes, middleware, response shapes; `GET /api/status` counts (total, enriched, pending) |
| `test_frontend.py` | Static file serving, HTML element IDs, CDN tags, JS function definitions, CSS selectors |
| `test_tts_chunking.py` | `chunk_text` (sentence/space/hard-split boundaries, `! `/ `? ` markers, last-boundary selection, empty-chunk filtering), `synthesize_chunk` (bytes-joining, error wrapping), `get_audio_duration` (mutagen delegation), `synthesize_article` (cache hit, stale-file recovery, 50 k-char cost guard, `TTSSynthesisError` propagation) |
| `test_cache.py` | `sweep_expired_cache` (single and batch expiry, settings-default TTL, missing-file tolerance, same-day boundary), `get_cache_stats` (empty, single-entry, multi-entry, post-sweep state) |
| `test_api_audio.py` | Audio status (uncached, cached with duration), stream 404 behaviour, stream success with reading-state side-effect, synthesis trigger (202 pending, 202 ready when cached, 404 for missing article) |
| `test_state.py` | State transitions to queued/listened/unread; `last_played_at` cleared on unread transition; UPSERT creates row when none exists; 422 on invalid status; 404 for missing article; queue endpoint returns only queued articles, returns empty array, excludes other statuses, orders by `updated_at ASC`; scheduler has exactly two jobs (`feed_refresh`, `cache_sweep`) with correct trigger types and interval/cron configuration; `_refresh_job` calls `enrich_all_unenriched` after `refresh_all_feeds` |
| `test_search.py` | `GET /api/search` returns matching articles by title and body text; returns empty array for unrecognised terms; returns 422 when `q` is missing; FTS5 triggers populate the virtual table on insert; articles without a `reading_state` row appear in results with status `"unread"` |

Fixtures live in `tests/fixtures/`. The RSS fixture (`sample_feed.xml`) contains three representative entries covering normal articles, missing fields, and audio enclosures.

---

## Windows SSL and redirect notes

Python distributed through the Microsoft Store does not automatically expose the Windows system certificate store to the `ssl` module. Without explicit configuration, every HTTPS request (to the Quanta Magazine RSS feeds and article pages) fails with `CERTIFICATE_VERIFY_FAILED`.

Voce addresses this with two declared dependencies:

- **`certifi`** — provides a bundled CA certificate bundle as a `.pem` file accessible via `certifi.where()`
- **`pip-system-certs`** — installs a `.pth` file that patches `certifi.where()` at Python startup to return the OS-native certificate bundle instead of certifi's bundled copy. On Windows this is the Windows Certificate Store, which is kept up to date by Windows Update and includes all intermediate certificates.

All `httpx.Client` instances that make external requests pass `verify=certifi.where()` explicitly. After `pip-system-certs` patches certifi, this resolves to the system store.

Additionally, httpx ≥ 0.20 does not follow HTTP redirects by default. The Quanta Magazine feed URLs issue 301 redirects; without `follow_redirects=True` the feeds appear to return empty results. All clients also pass `follow_redirects=True` for this reason.

If you encounter SSL errors during development on a non-Windows platform, ensure the `pip-system-certs` package is installed and that your Python environment has access to the system CA store. On macOS, running `pip install certifi` and the `/Applications/Python 3.x/Install Certificates.command` script (if present) should resolve the issue.

---

## Test philosophy

Tests use real SQLite (in-memory or temporary file) — the database is never mocked. This catches schema errors, trigger bugs, and FK constraint issues that an in-memory dict mock would miss.

Feed tests use the XML fixture rather than making live HTTP requests. HTTP calls are intercepted via `httpx`'s transport mocking.

API and frontend tests both use FastAPI's `TestClient`. All `TestClient` instances supply `headers={"host": "127.0.0.1:8765"}` so that `LocalhostOnlyMiddleware` admits the test requests — this applies to static file requests (`/static/app.js`, `/static/styles.css`) as well as JSON API calls.

Frontend tests verify structure rather than behaviour: they fetch the served files as text and use `in` membership checks (for element IDs, CDN URLs, function names, CSS selectors) and `re.search` (for `PAGE_SIZE = 30`). This approach confirms the files are wired correctly without a JavaScript runtime.

### Testing the audio API layer

`tests/test_api_audio.py` follows the same `TestClient` + in-memory SQLite fixture pattern as `test_api.py`. An additional `client_with_audio_cache` fixture pre-seeds an `audio_cache` row pointing to a real on-disk stub file (via `tmp_path`) and a `reading_state` row for the test article. The fixture yields `(client, conn)` so tests can assert database side-effects after the request:

```python
def test_audio_stream_cached_success(client_with_audio_cache):
    c, conn = client_with_audio_cache
    resp = c.get("/api/articles/art1/audio/stream")
    assert resp.status_code == 200
    row = conn.execute(
        "SELECT status FROM reading_state WHERE article_id='art1'"
    ).fetchone()
    assert row["status"] == "listened"
```

The synthesis trigger endpoint dispatches `synthesize_article()` to a background thread, so tests patch `voce.api.synthesize_article` to prevent real ElevenLabs calls:

```python
with patch("voce.api.synthesize_article"):
    resp = client.post("/api/articles/art1/audio")
assert resp.status_code == 202
assert resp.json()["status"] == "pending"
```

An `autouse` fixture clears `voce.api._synthesis_in_progress` before and after every test to prevent cross-test state leakage.

To test the stale-row recovery path, delete the stub MP3 file before issuing the request. The endpoint should remove the orphaned `audio_cache` row and return `cached: false` (for the status endpoint) or `404` (for the stream endpoint).

### Testing the TTS layer

TTS tests never call ElevenLabs. Every test that exercises `synthesize_chunk` or `synthesize_article` uses one of two mocking strategies:

**Mocking the ElevenLabs client class:**

```python
@patch("voce.tts.ElevenLabs")
def test_synthesize_article_writes_file_and_inserts_cache(mock_elevenlabs_cls, mem_conn_with_article, tmp_path):
    mock_client = MagicMock()
    mock_client.text_to_speech.convert.return_value = iter([b"\xff\xfb" + b"\x00" * 100])
    mock_elevenlabs_cls.return_value = mock_client
    ...
```

**Mocking mutagen directly** (for `get_audio_duration` or to avoid needing valid MP3 bytes):

```python
with patch("voce.tts.get_audio_duration", return_value=5.0):
    out_path = synthesize_article("art1", conn)

# or, to test get_audio_duration itself:
mock_audio = MagicMock()
mock_audio.info.length = 42.5
with patch("voce.tts.MP3", return_value=mock_audio):
    result = get_audio_duration(b"fake-bytes")
```

**Isolating disk writes:** Swap `cfg.settings.audio_cache_dir` to `tmp_path` before calling `synthesize_article`, and restore it in a `finally` block. pytest cleans up `tmp_path` automatically.

**Testing the cost guard:** Set `body_text` to a string longer than 50,000 characters via an `UPDATE` on the in-memory connection, then assert `ArticleTextMissingError` is raised. No network access is needed.

---

## Code conventions

### SQL

- Parameterised queries only. Never use f-strings or string concatenation to build SQL.
- SQL keywords uppercase: `SELECT`, `FROM`, `WHERE`, `INSERT OR IGNORE`, etc.
- No ORM. The schema is in `db.py`; queries are in the module that owns the relevant operation.

```python
# Correct
conn.execute("SELECT id FROM articles WHERE section = ?", (section,))

# Never
conn.execute(f"SELECT id FROM articles WHERE section = '{section}'")
```

### Logging

- Use `loguru` everywhere. Never use `print()` (except in the very first bootstrap before loguru is configured) and never use Python's stdlib `logging` module.
- Log at the right level: `INFO` for normal events, `WARNING` for recoverable problems, `ERROR` for failures that require attention.

```python
from loguru import logger

logger.info("Feed '{}' ingested {} articles", slug, inserted)
logger.warning("Article {} could not be enriched: {}", article_id, exc)
logger.error("Feed '{}' failed after {} retries: {}", slug, _MAX_RETRIES, exc)
```

### Error handling

- Raise domain exceptions from `voce/exceptions.py` in ingestion, enrichment, and synthesis code.
- The API layer translates domain exceptions into HTTP responses. Do not raise `HTTPException` outside of `api.py`.
- Never catch `Exception` silently. If you swallow an exception, log it first.

### Async

- FastAPI route functions are `async`. All database calls are delegated to a thread-pool executor:

```python
@app.get("/api/articles")
async def list_articles(conn: ConnDep) -> PaginatedArticles:
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _query_articles, conn, section, ...)
    return result
```

- Do not use `asyncio.run()` inside a route. Do not use `async with` with `sqlite3`.
- Synthesis and enrichment are synchronous operations. They are called from background scheduler jobs (which run in threads) or from routes via `run_in_executor`.

### Module boundaries

- `feeds.py` knows nothing about TTS or audio.
- `article.py` knows nothing about the API or scheduler.
- `tts.py` knows nothing about feeds or the API.
- `api.py` knows about everything but owns no business logic — routes are wiring, not algorithms.
- `config.py` is imported by all modules. It never imports from any other Voce module.

---

## CLI flags

The `python -m voce` entry point accepts the following flags:

| Flag | Description |
|------|-------------|
| `--host` | Bind address (default: `127.0.0.1`) |
| `--port` | Port number (default: `8765`) |
| `--log-level` | Log level passed to both uvicorn and loguru (default: `INFO`) |
| `--refresh-now` | Fetch all feeds once, print per-section `(inserted, skipped)` counts, and exit. Does not start the server. Useful for bootstrapping the database before the first browser session. |
| `--sweep-cache` | Delete audio cache entries older than `AUDIO_CACHE_TTL_DAYS` days, print the count, and exit. Does not start the server. |
| `--no-browser` | Skip `webbrowser.open(...)` after server startup. Useful when running headless or in a terminal multiplexer. |

On a normal startup (no early-exit flags), two loguru sinks are installed before uvicorn starts:

1. **stderr** — level from `--log-level`, format `HH:mm:ss LEVEL   module: message`
2. **`data/voce.log`** — level `DEBUG`, rotated at 10 MB, retained for 7 days

---

## Extending the codebase

### Adding a new section

Add a new entry to `QUANTA_FEEDS` in `feeds.py` and a new entry to `SECTION_LABELS` in `api.py`. No other changes are required — the schema, API endpoints, and UI all handle arbitrary section slugs.

### Adding a new API endpoint

1. Write the SQL query as a named function in the relevant domain module (e.g. `article.py`)
2. Add a Pydantic response model to `api.py` if needed
3. Add the route function in `api.py`, using `ConnDep` for the database connection
4. Write tests in `test_api.py`

### Extending the database schema

1. Add the new column, table, index, or trigger to the DDL string in `db.py`
2. Update the relevant dataclass `from_row()` in `models.py` if a new column is on an existing table
3. For new columns on existing tables, call `_add_column_if_missing(conn, table, column, col_type)` at the end of `bootstrap_schema()` — this is idempotent and handles pre-existing databases

The DDL uses `IF NOT EXISTS` for tables and indexes, so new tables and indexes are safe to add without a migration. New columns on existing tables use the `_add_column_if_missing()` helper rather than a separate migration script, because `bootstrap_schema()` runs on every startup.

### Modifying the frontend

The frontend has no build step. Edit the files directly and reload the browser — the server does not need to restart for static file changes.

| File | Contents |
|------|----------|
| `voce/static/index.html` | Layout shell, CDN script tags, element IDs |
| `voce/static/app.js` | All application behaviour — state, data fetching, DOM rendering |
| `voce/static/styles.css` | Custom component styles that complement Tailwind utilities |

**Adding a new element ID**: Declare it in `index.html` first, then reference it by ID in `app.js`. If the element is used in JavaScript-generated markup (not in the static shell), no change to `index.html` is needed.

**Adding a new CSS class**: Add it to `styles.css`. Tailwind utility classes are applied inline in `app.js` template literals; `styles.css` is reserved for classes that cannot be expressed as Tailwind utilities (e.g. `.article-card:hover`, `.prose`).

**Testing frontend changes**: `tests/test_frontend.py` verifies that required element IDs, CDN tags, JavaScript function names, and CSS selectors are present in the served files. If you rename a public function or element ID, update the corresponding test assertion.

---

## Project layout

```text
voce/
├── pyproject.toml          Project metadata, dependencies, tool config
├── .env.example            Environment variable template
├── voce/                   Python package
│   ├── __init__.py         Package version
│   ├── __main__.py         CLI entry point
│   ├── config.py           Settings
│   ├── db.py               Database connection and schema
│   ├── models.py           Row dataclasses
│   ├── exceptions.py       Custom exceptions
│   ├── feeds.py            RSS ingestion
│   ├── article.py          HTML enrichment and text cleaning
│   ├── tts.py              TTS synthesis
│   ├── cache.py            Audio cache management
│   ├── scheduler.py        Background job scheduling
│   ├── api.py              FastAPI application
│   └── static/
│       ├── index.html      Browser UI
│       ├── app.js          JavaScript
│       └── styles.css      Custom CSS
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   └── sample_feed.xml
│   └── test_*.py
├── data/                   Runtime data (gitignored)
│   ├── voce.db
│   ├── audio_cache/
│   └── voce.log
└── docs/                   This documentation
```
