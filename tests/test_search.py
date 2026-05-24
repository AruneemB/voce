import sqlite3

import pytest
from fastapi.testclient import TestClient

from voce.api import app, get_conn
from voce.db import bootstrap_schema


@pytest.fixture
def client():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_schema(conn)
    conn.execute(
        "INSERT INTO articles (id, section, title, published_at, url, body_html, body_text) "
        "VALUES ('a1','physics','Quantum Entanglement','2024-01-01T00:00:00Z','https://x.com/1','','Particles entangle at a distance.')"
    )
    conn.execute(
        "INSERT INTO articles (id, section, title, published_at, url, body_html, body_text) "
        "VALUES ('a2','biology','Cell Division','2024-01-02T00:00:00Z','https://x.com/2','','Mitosis and meiosis.')"
    )
    conn.execute("INSERT INTO reading_state (article_id, status) VALUES ('a1', 'unread')")
    conn.execute("INSERT INTO reading_state (article_id, status) VALUES ('a2', 'unread')")
    conn.commit()
    app.dependency_overrides[get_conn] = lambda: conn
    with TestClient(app, headers={"host": "127.0.0.1:8765"}) as c:
        yield c
    app.dependency_overrides.clear()
    conn.close()


def test_search_by_title_returns_matching_article(client):
    resp = client.get("/api/search?q=Quantum")
    assert resp.status_code == 200
    data = resp.json()
    assert any("Quantum" in item["title"] for item in data)


def test_search_returns_no_results_for_unknown_term(client):
    resp = client.get("/api/search?q=zzznomatchzzz")
    assert resp.status_code == 200
    assert resp.json() == []


def test_search_by_body_text(client):
    resp = client.get("/api/search?q=Mitosis")
    assert resp.status_code == 200
    data = resp.json()
    assert any(item["id"] == "a2" for item in data)


def test_search_missing_q_returns_422(client):
    resp = client.get("/api/search")
    assert resp.status_code == 422
