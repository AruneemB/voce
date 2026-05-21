import sqlite3
import pytest
from voce.db import get_connection, bootstrap_schema


@pytest.fixture
def mem_conn():
    """In-memory SQLite connection with schema bootstrapped."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_schema(conn)
    yield conn
    conn.close()


def test_bootstrap_creates_articles_table(mem_conn):
    tables = {r[0] for r in mem_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "articles" in tables


def test_bootstrap_creates_all_tables(mem_conn):
    tables = {r[0] for r in mem_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for expected in ("articles", "article_topics", "reading_state", "audio_cache"):
        assert expected in tables, f"Missing table: {expected}"


def test_reading_state_check_constraint_rejects_invalid_status(mem_conn):
    mem_conn.execute(
        "INSERT INTO articles (id, section, title, published_at, url, body_html, body_text) "
        "VALUES (?,?,?,?,?,?,?)",
        ("a1", "physics", "T", "2024-01-01T00:00:00Z", "https://example.com/1", "", ""),
    )
    mem_conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        mem_conn.execute(
            "INSERT INTO reading_state (article_id, status) VALUES (?, ?)",
            ("a1", "invalid-status"),
        )
        mem_conn.commit()


def test_fk_cascade_deletes_audio_cache(mem_conn):
    mem_conn.execute(
        "INSERT INTO articles (id, section, title, published_at, url, body_html, body_text) "
        "VALUES (?,?,?,?,?,?,?)",
        ("a2", "physics", "T2", "2024-01-02T00:00:00Z", "https://example.com/2", "", ""),
    )
    mem_conn.execute(
        "INSERT INTO audio_cache (article_id, file_path, voice_id) VALUES (?,?,?)",
        ("a2", "data/audio_cache/a2.mp3", "voice-xyz"),
    )
    mem_conn.commit()
    mem_conn.execute("DELETE FROM articles WHERE id=?", ("a2",))
    mem_conn.commit()
    row = mem_conn.execute("SELECT * FROM audio_cache WHERE article_id=?", ("a2",)).fetchone()
    assert row is None


def test_get_connection_returns_row_factory():
    conn = get_connection()
    conn.execute("CREATE TABLE IF NOT EXISTS _test (x INTEGER)")
    conn.execute("INSERT INTO _test VALUES (42)")
    row = conn.execute("SELECT x FROM _test").fetchone()
    assert row["x"] == 42
    conn.close()
