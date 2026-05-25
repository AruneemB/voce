"""Quanta Magazine RSS feed ingestion and article upsert logic."""

import hashlib
import sqlite3
import time
from datetime import datetime

import certifi
import feedparser
import httpx
from loguru import logger

from voce.exceptions import FeedFetchError

QUANTA_FEEDS: dict[str, str] = {
    "physics": "https://api.quantamagazine.org/feed/?post_type=post&category=physics",
    "mathematics": "https://api.quantamagazine.org/feed/?post_type=post&category=mathematics",
    "biology": "https://api.quantamagazine.org/feed/?post_type=post&category=biology",
    "computer-science": "https://api.quantamagazine.org/feed/?post_type=post&category=computer-science",
}
_USER_AGENT = "Voce/0.1 (personal TTS companion; +local)"
_TIMEOUT_SEC = 15
_MAX_RETRIES = 3


def fetch_feed(slug: str, url: str, client: httpx.Client) -> feedparser.FeedParserDict:
    """GET an RSS feed URL and return parsed content, retrying on transient failures."""
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = client.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT_SEC)
        except httpx.TimeoutException as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise FeedFetchError(slug, url, exc) from exc

        if response.status_code == 404:
            logger.warning("Feed '{}' returned 404: {}", slug, url)
            raise FeedFetchError(slug, url, ValueError(f"HTTP 404"))
        if 400 <= response.status_code < 500:
            raise FeedFetchError(slug, url, ValueError(f"HTTP {response.status_code}"))
        if response.status_code >= 500:
            last_exc = ValueError(f"HTTP {response.status_code}")
            if attempt < _MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise FeedFetchError(slug, url, last_exc)

        return feedparser.parse(response.text)

    raise FeedFetchError(slug, url, last_exc)


def parse_entries(slug: str, parsed: feedparser.FeedParserDict) -> list[dict]:
    """Extract and normalise article dicts from a parsed RSS feed."""
    results = []
    for entry in parsed.entries:
        url = entry.get("link", "")
        article_id = hashlib.sha256(url.encode()).hexdigest()[:16]

        if entry.get("published_parsed"):
            published_at = datetime(*entry.published_parsed[:6]).isoformat() + "Z"
        else:
            published_at = datetime.utcnow().isoformat() + "Z"

        audio_url = None
        for enclosure in entry.get("enclosures", []):
            if enclosure.get("type", "").startswith("audio/"):
                audio_url = enclosure.get("url")
                break

        results.append({
            "article_id": article_id,
            "section": slug,
            "title": entry.get("title", "Untitled"),
            "author": entry.get("author", "Unknown"),
            "published_at": published_at,
            "url": url,
            "summary": entry.get("summary", ""),
            "quanta_audio_url": audio_url,
        })
    return results


def upsert_articles(
    entries: list[dict], conn: sqlite3.Connection
) -> tuple[int, int]:
    """Insert new articles (and reading_state rows) into the DB, ignoring duplicates."""
    inserted = 0
    skipped = 0
    cur = conn.cursor()
    for e in entries:
        cur.execute(
            """
            INSERT OR IGNORE INTO articles
                (id, section, title, author, published_at, url, summary, quanta_audio_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                e["article_id"],
                e["section"],
                e["title"],
                e["author"],
                e["published_at"],
                e["url"],
                e["summary"],
                e["quanta_audio_url"],
            ),
        )
        if cur.rowcount == 1:
            inserted += 1
            conn.execute(
                "INSERT OR IGNORE INTO reading_state (article_id, status) VALUES (?, 'unread')",
                (e["article_id"],),
            )
        else:
            skipped += 1
    conn.commit()
    return inserted, skipped


def refresh_all_feeds(conn: sqlite3.Connection) -> dict[str, tuple[int, int]]:
    """Fetch, parse, and upsert all Quanta Magazine feeds; return per-slug counts."""
    results: dict[str, tuple[int, int]] = {}
    with httpx.Client(headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT_SEC, verify=certifi.where(), follow_redirects=True) as client:
        for slug, url in QUANTA_FEEDS.items():
            try:
                parsed = fetch_feed(slug, url, client)
                entries = parse_entries(slug, parsed)
                inserted, skipped = upsert_articles(entries, conn)
                results[slug] = (inserted, skipped)
            except FeedFetchError as exc:
                logger.error("Feed '{}' failed: {}", slug, exc)
                results[slug] = (0, 0)
    logger.info("Feed refresh complete: {}", results)
    return results
