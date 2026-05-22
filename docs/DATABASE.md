# Database

Voce stores all state in a single SQLite file at `data/voce.db`. The schema is bootstrapped automatically on first run and is safe to re-run on an existing database (all DDL uses `IF NOT EXISTS`).

---

## Design philosophy

- **No ORM.** All queries are raw SQL, written explicitly. This keeps the database layer auditable — you can read `db.py` and know exactly what is in the database.
- **Parameterised queries only.** No f-strings, no string concatenation in SQL. Every value is passed as a parameter.
- **SQL keywords uppercase.** Convention throughout the codebase for readability.
- **Synchronous access.** The `sqlite3` standard library module is used directly. FastAPI routes delegate DB calls to a thread-pool executor via `asyncio.run_in_executor()`, so the event loop is never blocked.
- **WAL mode.** `PRAGMA journal_mode=WAL` is set on every connection for better concurrent read performance.
- **Foreign keys enforced.** `PRAGMA foreign_keys=ON` is set on every connection.

---

## Tables

### `articles`

The central table. One row per Quanta Magazine article.

```sql
CREATE TABLE IF NOT EXISTS articles (
    id               TEXT PRIMARY KEY,
    section          TEXT NOT NULL,
    title            TEXT NOT NULL,
    author           TEXT,
    published_at     TEXT NOT NULL,
    url              TEXT NOT NULL UNIQUE,
    summary          TEXT,
    body_html        TEXT NOT NULL DEFAULT '',
    body_text        TEXT NOT NULL DEFAULT '',
    quanta_audio_url TEXT,
    ingested_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
```

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | TEXT | No | 16-char hex string derived from `sha256(url)`. Stable and reproducible. |
| `section` | TEXT | No | Section slug: `physics`, `mathematics`, `biology`, or `computer-science` |
| `title` | TEXT | No | Article title from the RSS feed |
| `author` | TEXT | Yes | Author name from the RSS feed |
| `published_at` | TEXT | No | ISO 8601 UTC timestamp from the RSS feed |
| `url` | TEXT | No | Canonical article URL. Has a UNIQUE constraint — this is how duplicates are detected. |
| `summary` | TEXT | Yes | RSS feed excerpt |
| `body_html` | TEXT | No | Raw HTML of the article body (empty until enriched) |
| `body_text` | TEXT | No | Prose-ready plain text after HTML cleanup and LaTeX conversion (empty until enriched) |
| `quanta_audio_url` | TEXT | Yes | Quanta's own narration URL if present in the RSS enclosure |
| `ingested_at` | TEXT | No | UTC timestamp when the article was first inserted |

**Upsert behaviour:** Articles are inserted with `INSERT OR IGNORE`. Re-ingesting a known article (same URL) has no effect — the existing row is not modified. This preserves any manual edits and avoids redundant work.

---

### `article_topics`

Maps articles to their topic tags. Many-to-many (an article can have multiple topics; a topic can apply to many articles).

```sql
CREATE TABLE IF NOT EXISTS article_topics (
    article_id  TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    topic       TEXT NOT NULL,
    PRIMARY KEY (article_id, topic)
);
```

| Column | Type | Description |
|--------|------|-------------|
| `article_id` | TEXT | FK to `articles.id`. Cascade-deleted when the article is removed. |
| `topic` | TEXT | Topic slug (e.g. `"black-holes"`, `"quantum-mechanics"`) |

Topics are extracted from the RSS feed's category tags and stored in their slugified form. The API derives display labels by title-casing the slug.

---

### `reading_state`

Tracks the playback status of each article. One row per article, created alongside the article on ingestion.

```sql
CREATE TABLE IF NOT EXISTS reading_state (
    article_id     TEXT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    status         TEXT NOT NULL DEFAULT 'unread'
                       CHECK(status IN ('unread','queued','listened')),
    last_played_at TEXT,
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
```

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `article_id` | TEXT | No | FK to `articles.id` (1:1 relationship) |
| `status` | TEXT | No | One of `unread`, `queued`, `listened`. Enforced by CHECK constraint. |
| `last_played_at` | TEXT | Yes | UTC timestamp of the last audio stream request |
| `updated_at` | TEXT | No | UTC timestamp of the last status change |

The `status` column has a CHECK constraint. An invalid value is rejected by SQLite before it reaches application code.

Article list queries LEFT JOIN this table and `COALESCE(rs.status, 'unread')` to treat articles without a `reading_state` row as unread (defence against rows created before the trigger existed).

---

### `audio_cache`

Records locally synthesised MP3 files. One row per article (synthesis is always with the configured voice ID).

```sql
CREATE TABLE IF NOT EXISTS audio_cache (
    article_id     TEXT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    file_path      TEXT NOT NULL,
    voice_id       TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    last_played_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    duration_sec   INTEGER
);
```

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `article_id` | TEXT | No | FK to `articles.id` |
| `file_path` | TEXT | No | Absolute or relative path to the MP3 file on disk |
| `voice_id` | TEXT | No | ElevenLabs voice ID used for synthesis |
| `created_at` | TEXT | No | When synthesis completed |
| `last_played_at` | TEXT | No | Updated on every stream request. Used by the cache sweep to determine expiry. |
| `duration_sec` | INTEGER | Yes | Audio duration in seconds (populated via mutagen after synthesis) |

**Cache expiry:** The sweep runs daily and deletes rows where `last_played_at < now - TTL`. The corresponding MP3 file is deleted from disk before the row is removed.

---

## FTS5 virtual table

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS fts_articles
    USING fts5(title, body_text, content='articles', content_rowid='rowid');
```

`fts_articles` is a content-table FTS5 index backed by `articles`. It indexes the `title` and `body_text` columns. The `content='articles'` directive means FTS5 does not store its own copy of the text — it reads from `articles` on demand.

Search queries use the standard FTS5 MATCH syntax. If the query string is not valid FTS5 syntax, the API falls back to a LIKE-based substring search.

---

## Triggers

Three triggers keep `fts_articles` in sync with `articles`:

```sql
-- After a new article is inserted
CREATE TRIGGER IF NOT EXISTS articles_ai
AFTER INSERT ON articles BEGIN
    INSERT INTO fts_articles(rowid, title, body_text)
    VALUES (new.rowid, new.title, new.body_text);
END;

-- After title or body_text is updated
CREATE TRIGGER IF NOT EXISTS articles_au
AFTER UPDATE OF title, body_text ON articles BEGIN
    INSERT INTO fts_articles(fts_articles, rowid, title, body_text)
    VALUES ('delete', old.rowid, old.title, old.body_text);
    INSERT INTO fts_articles(rowid, title, body_text)
    VALUES (new.rowid, new.title, new.body_text);
END;

-- After an article is deleted
CREATE TRIGGER IF NOT EXISTS articles_ad
AFTER DELETE ON articles BEGIN
    INSERT INTO fts_articles(fts_articles, rowid, title, body_text)
    VALUES ('delete', old.rowid, old.title, old.body_text);
END;
```

The FTS5 "delete" command (inserting a row with the special `fts_articles` column set to `'delete'`) removes the entry from the index. The update trigger issues a delete followed by an insert to atomically replace the indexed content.

---

## Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_articles_section      ON articles(section);
CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_article_topics_topic  ON article_topics(topic);
CREATE INDEX IF NOT EXISTS idx_reading_state_status  ON reading_state(status);
```

| Index | Supports |
|-------|----------|
| `idx_articles_section` | `GET /api/articles?section=…` filter |
| `idx_articles_published_at` | `ORDER BY published_at DESC` on article list queries |
| `idx_article_topics_topic` | `GET /api/articles?topic=…` EXISTS subquery |
| `idx_reading_state_status` | `GET /api/queue` (status = 'queued') and section unread counts |

---

## Data lifecycle

```
RSS feed ingested
    → article row created (body_html='', body_text='')
    → reading_state row created (status='unread')

Enrichment runs
    → article.body_html and article.body_text populated
    → FTS5 index updated via articles_au trigger

User requests audio
    → audio_cache row checked
    → if missing: synthesis pipeline runs, MP3 written to disk
    → audio_cache row created
    → last_played_at updated on every stream

User updates reading status
    → reading_state.status updated
    → reading_state.updated_at updated

Daily cache sweep runs
    → audio_cache rows with stale last_played_at deleted
    → corresponding MP3 files deleted from disk
```
