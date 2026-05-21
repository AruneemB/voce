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
        "VALUES (?,?,?,?,?,?,?)",
        ("art1", "physics", "Test Article", "2024-01-01T00:00:00Z", "https://example.com/1", "", "Body text here."),
    )
    conn.execute("INSERT INTO reading_state (article_id, status) VALUES ('art1', 'unread')")
    conn.commit()

    app.dependency_overrides[get_conn] = lambda: conn
    with TestClient(app, headers={"host": "127.0.0.1:8765"}) as c:
        yield c
    app.dependency_overrides.clear()
    conn.close()


def test_sections_returns_list(client):
    resp = client.get("/api/sections")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_sections_always_includes_all_four(client):
    resp = client.get("/api/sections")
    slugs = {s["section"] for s in resp.json()}
    assert slugs == {"physics", "mathematics", "biology", "computer-science"}


def test_articles_returns_list(client):
    resp = client.get("/api/articles")
    assert resp.status_code == 200
    assert "items" in resp.json()


def test_articles_section_filter(client):
    resp = client.get("/api/articles?section=physics")
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["section"] == "physics"


def test_article_detail_returns_body_text(client):
    resp = client.get("/api/articles/art1")
    assert resp.status_code == 200
    assert resp.json()["body_text"] == "Body text here."
