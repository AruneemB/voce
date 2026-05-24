import sqlite3

import pytest
from fastapi.testclient import TestClient

from voce.api import app, get_conn
from voce.db import bootstrap_schema


@pytest.fixture
def client():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_schema(conn)
    conn.execute(
        "INSERT INTO articles (id, section, title, published_at, url, body_html, body_text) "
        "VALUES ('art1','physics','T','2024-01-01T00:00:00Z','https://x.com','','.')"
    )
    conn.execute("INSERT INTO reading_state (article_id, status) VALUES ('art1', 'unread')")
    conn.commit()
    app.dependency_overrides[get_conn] = lambda: conn
    with TestClient(app, headers={"host": "127.0.0.1:8765"}) as c:
        yield c
    app.dependency_overrides.clear()
    conn.close()


def test_state_transition_to_queued(client):
    resp = client.post("/api/articles/art1/state", json={"status": "queued"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


def test_state_transition_to_listened(client):
    resp = client.post("/api/articles/art1/state", json={"status": "listened"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "listened"


def test_state_transition_to_unread_clears_last_played(client):
    client.post("/api/articles/art1/state", json={"status": "listened"})
    resp = client.post("/api/articles/art1/state", json={"status": "unread"})
    assert resp.status_code == 200
    assert resp.json()["last_played_at"] is None


def test_state_invalid_value_returns_422(client):
    resp = client.post("/api/articles/art1/state", json={"status": "invalid"})
    assert resp.status_code == 422


def test_state_404_for_missing_article(client):
    resp = client.post("/api/articles/nonexistent/state", json={"status": "queued"})
    assert resp.status_code == 404


def test_queue_returns_only_queued(client):
    client.post("/api/articles/art1/state", json={"status": "queued"})
    resp = client.get("/api/queue")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["status"] == "queued"


def test_scheduler_has_two_jobs():
    from voce.scheduler import build_scheduler
    s = build_scheduler(lambda: None)
    assert len(s.get_jobs()) == 2
    job_ids = {j.id for j in s.get_jobs()}
    assert "feed_refresh" in job_ids
    assert "cache_sweep" in job_ids
