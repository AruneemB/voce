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

    previous_override = app.dependency_overrides.get(get_conn)
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        with TestClient(app, headers={"host": "127.0.0.1:8765"}) as c:
            yield c
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_conn, None)
        else:
            app.dependency_overrides[get_conn] = previous_override
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
    items = resp.json()["items"]
    assert items, "Expected at least one article for section=physics"
    for item in items:
        assert item["section"] == "physics"


def test_article_detail_returns_body_text(client):
    resp = client.get("/api/articles/art1")
    assert resp.status_code == 200
    assert resp.json()["body_text"] == "Body text here."


def test_article_detail_404_for_missing(client):
    resp = client.get("/api/articles/does-not-exist")
    assert resp.status_code == 404


def test_topics_returns_list(client):
    resp = client.get("/api/topics")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_localhost_middleware_blocks_external_host(client):
    resp = client.get("/api/sections", headers={"host": "evil.com"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# /api/status tests
# ---------------------------------------------------------------------------


def test_status_returns_200(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200


def test_status_response_shape(client):
    data = client.get("/api/status").json()
    assert "total_articles" in data
    assert "enriched" in data
    assert "pending_enrichment" in data


def test_status_counts_enriched_article(client):
    # The fixture inserts one article with body_text "Body text here." — enriched.
    data = client.get("/api/status").json()
    assert data["total_articles"] == 1
    assert data["enriched"] == 1
    assert data["pending_enrichment"] == 0


def test_status_counts_unenriched_article():
    """An article with empty body_text appears in pending_enrichment."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_schema(conn)
    conn.execute(
        "INSERT INTO articles (id, section, title, published_at, url, body_html, body_text) "
        "VALUES (?,?,?,?,?,?,?)",
        ("empty1", "physics", "No Body", "2024-01-01T00:00:00Z", "https://example.com/2", "", ""),
    )
    conn.commit()

    previous = app.dependency_overrides.get(get_conn)
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        with TestClient(app, headers={"host": "127.0.0.1:8765"}) as c:
            data = c.get("/api/status").json()
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_conn, None)
        else:
            app.dependency_overrides[get_conn] = previous
        conn.close()

    assert data["total_articles"] == 1
    assert data["enriched"] == 0
    assert data["pending_enrichment"] == 1


def test_status_pending_plus_enriched_equals_total():
    """pending_enrichment + enriched must always equal total_articles."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_schema(conn)
    conn.execute(
        "INSERT INTO articles (id, section, title, published_at, url, body_html, body_text) "
        "VALUES ('e1','physics','T1','2024-01-01T00:00:00Z','https://example.com/e1','','Enriched.')"
    )
    conn.execute(
        "INSERT INTO articles (id, section, title, published_at, url, body_html, body_text) "
        "VALUES ('e2','mathematics','T2','2024-01-01T00:00:00Z','https://example.com/e2','','')"
    )
    conn.commit()

    previous = app.dependency_overrides.get(get_conn)
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        with TestClient(app, headers={"host": "127.0.0.1:8765"}) as c:
            data = c.get("/api/status").json()
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_conn, None)
        else:
            app.dependency_overrides[get_conn] = previous
        conn.close()

    assert data["enriched"] + data["pending_enrichment"] == data["total_articles"]
