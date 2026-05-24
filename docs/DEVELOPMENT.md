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
| `test_feeds.py` | RSS parsing, upsert logic, retry behaviour |
| `test_article.py` | HTML cleaning, LaTeX substitutions, preamble format |
| `test_api.py` | FastAPI routes, middleware, response shapes |
| `test_frontend.py` | Static file serving, HTML element IDs, CDN tags, JS function definitions, CSS selectors |
| `test_tts_chunking.py` | `chunk_text` (sentence/space/hard-split boundaries, `! `/ `? ` markers, last-boundary selection, empty-chunk filtering), `synthesize_chunk` (bytes-joining, error wrapping), `get_audio_duration` (mutagen delegation), `synthesize_article` (cache hit, stale-file recovery, 50 k-char cost guard, `TTSSynthesisError` propagation) |
| `test_cache.py` | `sweep_expired_cache` (single and batch expiry, settings-default TTL, missing-file tolerance, same-day boundary), `get_cache_stats` (empty, single-entry, multi-entry, post-sweep state) |

Fixtures live in `tests/fixtures/`. The RSS fixture (`sample_feed.xml`) contains three representative entries covering normal articles, missing fields, and audio enclosures.

---

## Test philosophy

Tests use real SQLite (in-memory or temporary file) — the database is never mocked. This catches schema errors, trigger bugs, and FK constraint issues that an in-memory dict mock would miss.

Feed tests use the XML fixture rather than making live HTTP requests. HTTP calls are intercepted via `httpx`'s transport mocking.

API and frontend tests both use FastAPI's `TestClient`. All `TestClient` instances supply `headers={"host": "127.0.0.1:8765"}` so that `LocalhostOnlyMiddleware` admits the test requests — this applies to static file requests (`/static/app.js`, `/static/styles.css`) as well as JSON API calls.

Frontend tests verify structure rather than behaviour: they fetch the served files as text and use `in` membership checks (for element IDs, CDN URLs, function names, CSS selectors) and `re.search` (for `PAGE_SIZE = 30`). This approach confirms the files are wired correctly without a JavaScript runtime.

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
3. If you are modifying an existing schema with production data, write a migration script in `scripts/`

The DDL uses `IF NOT EXISTS` for tables and indexes, so new tables and indexes are safe to add without a migration. New columns on existing tables require an `ALTER TABLE ... ADD COLUMN` migration.

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
