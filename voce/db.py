"""SQLite connection factory and schema bootstrap for Voce."""

import re
import sqlite3
from voce.config import settings

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED_COL_TYPES = {"INTEGER", "TEXT", "REAL", "BLOB", "NUMERIC"}


def _safe_ident(name: str) -> str:
    """Return *name* quoted for use as a SQL identifier, or raise ValueError."""
    if not _IDENT_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return f'"{name}"'

_DDL = """
CREATE TABLE IF NOT EXISTS articles (
    id              TEXT PRIMARY KEY,
    section         TEXT NOT NULL,
    title           TEXT NOT NULL,
    author          TEXT,
    published_at    TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,
    summary         TEXT,
    body_html       TEXT NOT NULL DEFAULT '',
    body_text       TEXT NOT NULL DEFAULT '',
    quanta_audio_url TEXT,
    ingested_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS article_topics (
    article_id  TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    topic       TEXT NOT NULL,
    PRIMARY KEY (article_id, topic)
);

CREATE TABLE IF NOT EXISTS reading_state (
    article_id      TEXT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'unread'
                        CHECK(status IN ('unread','queued','listened')),
    last_played_at  TEXT,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS audio_cache (
    article_id      TEXT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    file_path       TEXT NOT NULL,
    voice_id        TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    last_played_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    duration_sec    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_articles_section       ON articles(section);
CREATE INDEX IF NOT EXISTS idx_articles_published_at  ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_article_topics_topic   ON article_topics(topic);
CREATE INDEX IF NOT EXISTS idx_reading_state_status   ON reading_state(status);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_articles
    USING fts5(title, body_text, content='articles', content_rowid='rowid');

CREATE TRIGGER IF NOT EXISTS articles_ai
AFTER INSERT ON articles BEGIN
    INSERT INTO fts_articles(rowid, title, body_text)
    VALUES (new.rowid, new.title, new.body_text);
END;

CREATE TRIGGER IF NOT EXISTS articles_au
AFTER UPDATE OF title, body_text ON articles BEGIN
    INSERT INTO fts_articles(fts_articles, rowid, title, body_text)
    VALUES ('delete', old.rowid, old.title, old.body_text);
    INSERT INTO fts_articles(rowid, title, body_text)
    VALUES (new.rowid, new.title, new.body_text);
END;

CREATE TRIGGER IF NOT EXISTS articles_ad
AFTER DELETE ON articles BEGIN
    INSERT INTO fts_articles(fts_articles, rowid, title, body_text)
    VALUES ('delete', old.rowid, old.title, old.body_text);
END;
"""


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, col_type: str
) -> None:
    """Add *column* to *table* only if it does not already exist.

    SQLite does not support ``ALTER TABLE … ADD COLUMN IF NOT EXISTS``, so we
    inspect ``PRAGMA table_info`` and conditionally issue the ``ALTER TABLE``.
    Idempotent; safe to call on every bootstrap.
    """
    col_type_upper = col_type.upper()
    if col_type_upper not in _ALLOWED_COL_TYPES:
        raise ValueError(f"Unsupported column type: {col_type!r}")
    safe_table = _safe_ident(table)
    safe_column = _safe_ident(column)
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({safe_table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {safe_table} ADD COLUMN {safe_column} {col_type_upper}")


def get_connection() -> sqlite3.Connection:
    """Open and configure a new SQLite connection. Caller is responsible for closing it."""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def bootstrap_schema(conn: sqlite3.Connection) -> None:
    """Create all tables, indexes, and triggers if they do not already exist."""
    conn.executescript(_DDL)
    _add_column_if_missing(conn, "articles", "quanta_audio_url", "TEXT")
    conn.commit()
