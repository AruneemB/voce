"""Tests for audio synthesis and playback API endpoints."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from voce.api import app, get_conn
from voce.db import bootstrap_schema


@pytest.fixture(autouse=True)
def clear_synthesis_state():
    """Ensure _synthesis_in_progress is empty before and after every test."""
    from voce.api import _synthesis_in_progress
    _synthesis_in_progress.clear()
    yield
    _synthesis_in_progress.clear()


@pytest.fixture
def client():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_schema(conn)
    conn.execute(
        "INSERT INTO articles (id, section, title, published_at, url, body_html, body_text) "
        "VALUES (?,?,?,?,?,?,?)",
        ("art1", "physics", "Test Article", "2024-01-01T00:00:00Z",
         "https://example.com/1", "", "Body text here."),
    )
    conn.execute("INSERT INTO reading_state (article_id, status) VALUES ('art1', 'unread')")
    conn.commit()

    previous = app.dependency_overrides.get(get_conn)
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        with TestClient(app, headers={"host": "127.0.0.1:8765"}) as c:
            yield c
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_conn, None)
        else:
            app.dependency_overrides[get_conn] = previous
        conn.close()


def test_audio_status_uncached(client):
    resp = client.get("/api/articles/art1/audio/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cached"] is False
    assert data["url"] is None
    assert data["pending"] is False


def test_audio_stream_404_when_uncached(client):
    resp = client.get("/api/articles/art1/audio/stream")
    assert resp.status_code == 404
