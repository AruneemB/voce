"""APScheduler background job setup for feed refresh and cache sweep."""

import sqlite3
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

from voce.cache import sweep_expired_cache
from voce.config import settings
from voce.feeds import refresh_all_feeds


def _refresh_job(conn_factory: Callable[[], sqlite3.Connection]) -> None:
    conn: sqlite3.Connection | None = None
    try:
        conn = conn_factory()
        results = refresh_all_feeds(conn)
        logger.info(f"Scheduled feed refresh complete: {results}")
    except Exception as exc:
        logger.error(f"Scheduled feed refresh failed: {exc}")
    finally:
        if conn is not None:
            conn.close()


def _sweep_job(conn_factory: Callable[[], sqlite3.Connection]) -> None:
    conn: sqlite3.Connection | None = None
    try:
        conn = conn_factory()
        count = sweep_expired_cache(conn)
        logger.info(f"Scheduled cache sweep removed {count} expired files")
    except Exception as exc:
        logger.error(f"Scheduled cache sweep failed: {exc}")
    finally:
        if conn is not None:
            conn.close()


def build_scheduler(conn_factory: Callable[[], sqlite3.Connection]) -> BackgroundScheduler:
    """Create and configure the APScheduler BackgroundScheduler. Does not start it."""
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _refresh_job,
        trigger="interval",
        minutes=settings.feed_refresh_minutes,
        args=[conn_factory],
        id="feed_refresh",
        name="Quanta feed refresh",
    )
    scheduler.add_job(
        _sweep_job,
        trigger="cron",
        hour=3,
        minute=0,
        args=[conn_factory],
        id="cache_sweep",
        name="Audio cache sweep",
    )
    return scheduler
