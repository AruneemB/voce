"""Audio cache expiry sweep and cache statistics."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from loguru import logger

from voce.config import settings


def sweep_expired_cache(conn: sqlite3.Connection, ttl_days: int | None = None) -> int:
    """Delete expired audio cache entries and their MP3 files from disk.

    A cache entry is expired when its ``last_played_at`` timestamp is older than
    *ttl_days* ago.  *ttl_days* defaults to ``settings.audio_cache_ttl_days``
    when not provided.  The value is coerced to ``int`` and must be
    non-negative; a negative value raises ``ValueError``.

    RFC3339 ``last_played_at`` values are normalised via SQLite's
    ``datetime()`` before comparison so that the ``T``/``Z`` separators in
    stored timestamps do not cause lexicographic comparison errors.

    MP3 files that have already been removed from disk are skipped silently.
    Returns the number of entries deleted.
    """
    if ttl_days is None:
        ttl_days = settings.audio_cache_ttl_days
    ttl_days = int(ttl_days)
    if ttl_days < 0:
        raise ValueError(f"ttl_days must be non-negative, got {ttl_days}")
    rows = conn.execute(
        "SELECT article_id, file_path FROM audio_cache"
        " WHERE datetime(last_played_at) < datetime('now', ?)",
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
    """Return a summary of the current audio cache state.

    Returns a dict with keys:

    * ``total_files`` — number of rows in ``audio_cache``
    * ``oldest_played_at`` — earliest ``last_played_at`` timestamp, or ``None``
    * ``newest_played_at`` — most recent ``last_played_at`` timestamp, or ``None``
    """
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
