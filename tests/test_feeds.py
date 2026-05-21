"""Tests for voce.feeds — all run offline via fixtures and mocks."""

import hashlib
import pathlib
import sqlite3
from unittest.mock import MagicMock, patch

import feedparser
import httpx
import pytest

from voce.db import bootstrap_schema
from voce.exceptions import FeedFetchError
from voce.feeds import fetch_feed, parse_entries, refresh_all_feeds, upsert_articles

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "sample_feed.xml"


@pytest.fixture
def parsed_feed() -> feedparser.FeedParserDict:
    return feedparser.parse(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def mem_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# parse_entries tests
# ---------------------------------------------------------------------------


def test_parse_entries_count(parsed_feed):
    entries = parse_entries("physics", parsed_feed)
    assert len(entries) == 3


def test_parse_entries_title(parsed_feed):
    entries = parse_entries("physics", parsed_feed)
    assert entries[0]["title"] == "The Mystery of Quantum Entanglement"


def test_parse_entries_no_guid_fallback(parsed_feed):
    """Article 2 has no <guid>; article_id must be derived from the link URL."""
    entries = parse_entries("physics", parsed_feed)
    link = "https://www.quantamagazine.org/black-holes-information-paradox-20240220/"
    expected_id = hashlib.sha256(link.encode()).hexdigest()[:16]
    assert entries[1]["article_id"] == expected_id


def test_parse_entries_audio_url(parsed_feed):
    """Article 2 has an audio enclosure; article 1 does not."""
    entries = parse_entries("physics", parsed_feed)
    assert entries[1]["quanta_audio_url"] == (
        "https://api.quantamagazine.org/audio/black-holes-information-paradox.mp3"
    )
    assert entries[0]["quanta_audio_url"] is None


# ---------------------------------------------------------------------------
# upsert_articles tests
# ---------------------------------------------------------------------------


def test_upsert_idempotent(parsed_feed, mem_conn):
    """First upsert inserts all rows; second upsert skips them all."""
    entries = parse_entries("physics", parsed_feed)

    inserted, skipped = upsert_articles(entries, mem_conn)
    assert inserted == 3
    assert skipped == 0

    inserted2, skipped2 = upsert_articles(entries, mem_conn)
    assert inserted2 == 0
    assert skipped2 == 3


# ---------------------------------------------------------------------------
# fetch_feed tests
# ---------------------------------------------------------------------------


def test_fetch_feed_timeout_raises():
    """Exhausting all retries on TimeoutException raises FeedFetchError."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.side_effect = httpx.TimeoutException("timed out")

    with patch("voce.feeds.time.sleep"):
        with pytest.raises(FeedFetchError) as exc_info:
            fetch_feed("physics", "https://example.com/feed", mock_client)

    assert exc_info.value.slug == "physics"
    # Should have attempted _MAX_RETRIES + 1 = 4 times total
    assert mock_client.get.call_count == 4


# ---------------------------------------------------------------------------
# refresh_all_feeds tests
# ---------------------------------------------------------------------------


def test_refresh_all_feeds_skips_failing(mem_conn):
    """A FeedFetchError for one feed is recorded as (0,0) and others continue."""
    good_parsed = feedparser.parse(FIXTURE_PATH.read_text(encoding="utf-8"))

    call_count = 0

    def fake_fetch(slug, url, client):
        nonlocal call_count
        call_count += 1
        if slug == "physics":
            raise FeedFetchError(slug, url, ValueError("boom"))
        return good_parsed

    with patch("voce.feeds.fetch_feed", side_effect=fake_fetch):
        results = refresh_all_feeds(mem_conn)

    assert results["physics"] == (0, 0)
    # Remaining three feeds should have ingested articles
    for slug in ("mathematics", "biology", "computer-science"):
        inserted, skipped = results[slug]
        assert inserted + skipped == 3
