import sqlite3
from pathlib import Path

import pytest

from voce.cache import get_cache_stats, sweep_expired_cache
from voce.db import bootstrap_schema


@pytest.fixture
def mem_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_schema(conn)
    conn.execute(
        "INSERT INTO articles (id, section, title, author, published_at, url, body_html, body_text) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("art1", "physics", "Test", "Author", "2024-01-01T00:00:00Z", "https://x.com/1", "", "Hello world."),
    )
    conn.execute(
        "INSERT INTO articles (id, section, title, author, published_at, url, body_html, body_text) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("art2", "physics", "Test 2", "Author", "2024-01-02T00:00:00Z", "https://x.com/2", "", "Another article."),
    )
    conn.commit()
    yield conn
    conn.close()


def _insert_cache_row(conn, article_id: str, file_path: str, last_played_at: str) -> None:
    conn.execute(
        "INSERT INTO audio_cache (article_id, file_path, voice_id, last_played_at) VALUES (?,?,?,?)",
        (article_id, file_path, "voice-test", last_played_at),
    )
    conn.commit()


# ── sweep_expired_cache tests ─────────────────────────────────────────────────

def test_sweep_returns_zero_when_cache_is_empty(mem_conn):
    count = sweep_expired_cache(mem_conn, ttl_days=30)
    assert count == 0


def test_sweep_deletes_expired_row_and_file(mem_conn, tmp_path):
    mp3 = tmp_path / "art1.mp3"
    mp3.write_bytes(b"fake-mp3")
    _insert_cache_row(mem_conn, "art1", str(mp3), "2000-01-01T00:00:00Z")

    count = sweep_expired_cache(mem_conn, ttl_days=1)

    assert count == 1
    assert not mp3.exists()
    row = mem_conn.execute("SELECT * FROM audio_cache WHERE article_id='art1'").fetchone()
    assert row is None


def test_sweep_does_not_delete_fresh_rows(mem_conn, tmp_path):
    mp3 = tmp_path / "art1.mp3"
    mp3.write_bytes(b"fake-mp3")
    _insert_cache_row(mem_conn, "art1", str(mp3), "2099-01-01T00:00:00Z")

    count = sweep_expired_cache(mem_conn, ttl_days=30)

    assert count == 0
    assert mp3.exists()
    row = mem_conn.execute("SELECT * FROM audio_cache WHERE article_id='art1'").fetchone()
    assert row is not None


def test_sweep_respects_custom_ttl_days(mem_conn, tmp_path):
    mp3_old = tmp_path / "art1.mp3"
    mp3_old.write_bytes(b"old")
    mp3_new = tmp_path / "art2.mp3"
    mp3_new.write_bytes(b"new")

    _insert_cache_row(mem_conn, "art1", str(mp3_old), "2000-01-01T00:00:00Z")
    _insert_cache_row(mem_conn, "art2", str(mp3_new), "2099-01-01T00:00:00Z")

    count = sweep_expired_cache(mem_conn, ttl_days=1)

    assert count == 1
    assert not mp3_old.exists()
    assert mp3_new.exists()


def test_sweep_handles_missing_file_gracefully(mem_conn):
    _insert_cache_row(mem_conn, "art1", "/nonexistent/path/art1.mp3", "2000-01-01T00:00:00Z")

    count = sweep_expired_cache(mem_conn, ttl_days=1)

    assert count == 1


def test_sweep_expires_same_day_older_timestamp(mem_conn, tmp_path):
    mp3 = tmp_path / "art1.mp3"
    mp3.write_bytes(b"fake-mp3")
    today = mem_conn.execute("SELECT date('now')").fetchone()[0]
    # Midnight today is earlier than now, so ttl_days=0 should treat it as expired.
    _insert_cache_row(mem_conn, "art1", str(mp3), f"{today}T00:00:00Z")

    count = sweep_expired_cache(mem_conn, ttl_days=0)

    assert count == 1
    assert not mp3.exists()


def test_sweep_raises_for_negative_ttl_days(mem_conn):
    with pytest.raises(ValueError, match="ttl_days must be non-negative"):
        sweep_expired_cache(mem_conn, ttl_days=-1)


# ── get_cache_stats tests ─────────────────────────────────────────────────────

def test_get_cache_stats_empty(mem_conn):
    stats = get_cache_stats(mem_conn)
    assert stats["total_files"] == 0
    assert stats["oldest_played_at"] is None
    assert stats["newest_played_at"] is None


def test_get_cache_stats_with_entries(mem_conn):
    _insert_cache_row(mem_conn, "art1", "/tmp/art1.mp3", "2024-01-01T00:00:00Z")
    _insert_cache_row(mem_conn, "art2", "/tmp/art2.mp3", "2024-06-01T00:00:00Z")

    stats = get_cache_stats(mem_conn)
    assert stats["total_files"] == 2
    assert stats["oldest_played_at"] == "2024-01-01T00:00:00Z"
    assert stats["newest_played_at"] == "2024-06-01T00:00:00Z"
