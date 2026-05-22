"""Audio cache expiry sweep and cache statistics."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from loguru import logger

from voce.config import settings


def sweep_expired_cache(conn: sqlite3.Connection, ttl_days: int | None = None) -> int:
    if ttl_days is None:
        ttl_days = settings.audio_cache_ttl_days
    rows = conn.execute(
        "SELECT article_id, file_path FROM audio_cache WHERE last_played_at < datetime('now', ?)",
        (f"-{ttl_days} days",),
    ).fetchall()
    ids = []
    for row in rows:
        Path(row["file_path"]).unlink(missing_ok=True)
        ids.append(row["article_id"])
    if ids:
        conn.execute(
            f"DELETE FROM audio_cache WHERE article_id IN ({','.join('?' * len(ids))})",
            ids,
        )
    conn.commit()
    count = len(ids)
    logger.info("Cache sweep: deleted {} expired audio files", count)
    return count


def get_cache_stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) as total, "
        "MIN(last_played_at) as oldest, "
        "MAX(last_played_at) as newest "
        "FROM audio_cache"
    ).fetchone()
    return {
        "total_files": row["total"],
        "oldest_played_at": row["oldest"],
        "newest_played_at": row["newest"],
    }
