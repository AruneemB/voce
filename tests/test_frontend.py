"""Tests for static file serving and HTML structure of the browsing UI."""

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
        "INSERT INTO articles (id, section, title, published_at, url, body_html, body_text, summary) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            "art1", "physics", "Test Article", "2024-06-01T00:00:00Z",
            "https://quantamagazine.org/test", "<p>body</p>", "Body text.\n\nSecond paragraph.", "A short summary.",
        ),
    )
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


# ── Static file serving ────────────────────────────────────────────────────────

def test_root_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_root_content_type_is_html(client):
    resp = client.get("/")
    assert "text/html" in resp.headers["content-type"]


def test_app_js_is_served(client):
    resp = client.get("/static/app.js")
    assert resp.status_code == 200


def test_styles_css_is_served(client):
    resp = client.get("/static/styles.css")
    assert resp.status_code == 200


# ── Required element IDs ───────────────────────────────────────────────────────

def test_html_has_sidebar_id(client):
    assert 'id="sidebar"' in client.get("/").text


def test_html_has_section_list_id(client):
    assert 'id="section-list"' in client.get("/").text


def test_html_has_topic_filter_id(client):
    assert 'id="topic-filter"' in client.get("/").text


def test_html_has_state_filters_id(client):
    assert 'id="state-filters"' in client.get("/").text


def test_html_has_article_list_id(client):
    assert 'id="article-list"' in client.get("/").text


def test_html_has_load_more_sentinel_id(client):
    assert 'id="load-more-sentinel"' in client.get("/").text


def test_html_has_article_detail_id(client):
    assert 'id="article-detail"' in client.get("/").text


def test_html_has_toast_container_id(client):
    assert 'id="toast-container"' in client.get("/").text


def test_html_has_search_input_id(client):
    assert 'id="search-input"' in client.get("/").text


# ── CDN script tags ────────────────────────────────────────────────────────────

def test_html_has_tailwind_cdn(client):
    assert 'src="https://cdn.tailwindcss.com"' in client.get("/").text


def test_html_has_htmx_cdn_url(client):
    assert "https://unpkg.com/htmx.org@1.9.10" in client.get("/").text


def test_html_has_htmx_integrity(client):
    assert "sha384-D1Kt99CQMDuVetoL1lrYwg5t+9QdHe7NLX/SoJYkXDFfX37iInKRy5ViYgSibmK" in client.get("/").text


# ── Content and form elements ──────────────────────────────────────────────────

def test_html_has_tagline(client):
    assert "a reading companion for Quanta Magazine" in client.get("/").text


def test_html_has_search_input_type(client):
    assert 'type="search"' in client.get("/").text


def test_html_links_app_js(client):
    assert "/static/app.js" in client.get("/").text


def test_html_links_styles_css(client):
    assert "/static/styles.css" in client.get("/").text
