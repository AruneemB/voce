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


# ── JavaScript structure ───────────────────────────────────────────────────────

@pytest.fixture
def js(client):
    return client.get("/static/app.js").text


def test_js_defines_loadSections(js):
    assert "function loadSections" in js or "async function loadSections" in js


def test_js_defines_loadArticles(js):
    assert "function loadArticles" in js or "async function loadArticles" in js


def test_js_defines_loadArticleDetail(js):
    assert "function loadArticleDetail" in js or "async function loadArticleDetail" in js


def test_js_defines_showToast(js):
    assert "function showToast" in js


def test_js_defines_triggerRefresh(js):
    assert "function triggerRefresh" in js or "async function triggerRefresh" in js


def test_js_has_currentSection(js):
    assert "currentSection" in js


def test_js_has_currentTopic(js):
    assert "currentTopic" in js


def test_js_has_currentStatus(js):
    assert "currentStatus" in js


def test_js_has_currentOffset(js):
    assert "currentOffset" in js


def test_js_page_size_is_30(js):
    import re
    assert re.search(r"PAGE_SIZE\s*=\s*30", js)


def test_js_references_api_sections(js):
    assert "/api/sections" in js


def test_js_references_api_articles(js):
    assert "/api/articles" in js


def test_js_accesses_items_field(js):
    assert ".items" in js


def test_js_uses_history_pushState(js):
    assert "history.pushState" in js


def test_js_uses_IntersectionObserver(js):
    assert "IntersectionObserver" in js


def test_js_has_DOMContentLoaded(js):
    assert "DOMContentLoaded" in js


# ── CSS structure ─────────────────────────────────────────────────────────────

@pytest.fixture
def css(client):
    return client.get("/static/styles.css").text


def test_css_has_prose_selector(css):
    assert ".prose" in css


def test_css_prose_max_width_70ch(css):
    assert "70ch" in css


def test_css_prose_font_family_georgia(css):
    assert "Georgia" in css


def test_css_has_article_card_selector(css):
    assert ".article-card" in css


def test_css_article_card_hover_background(css):
    assert "#f0f9ff" in css


def test_css_has_status_badge_selector(css):
    assert ".status-badge" in css


def test_css_has_status_unread(css):
    assert ".status-unread" in css


def test_css_status_unread_colors(css):
    assert "#dbeafe" in css
    assert "#1d4ed8" in css


def test_css_has_status_queued(css):
    assert ".status-queued" in css


def test_css_status_queued_colors(css):
    assert "#fef9c3" in css
    assert "#854d0e" in css


def test_css_has_status_listened(css):
    assert ".status-listened" in css


def test_css_status_listened_colors(css):
    assert "#dcfce7" in css
    assert "#166534" in css


def test_css_has_toast_container(css):
    assert "#toast-container" in css


def test_css_toast_container_is_fixed(css):
    block = css[css.find("#toast-container"):]
    assert "fixed" in block


def test_css_toast_z_index_9999(css):
    assert "9999" in css


def test_css_has_quanta_link(css):
    assert ".quanta-link" in css


# ── XSS mitigations ───────────────────────────────────────────────────────────

def test_js_defines_escapeHtml(js):
    assert "function escapeHtml" in js


def test_js_escapeHtml_encodes_lt(js):
    assert "'&lt;'" in js or '"&lt;"' in js


def test_js_escapeHtml_encodes_gt(js):
    assert "'&gt;'" in js or '"&gt;"' in js


def test_js_escapeHtml_encodes_amp(js):
    assert "'&amp;'" in js or '"&amp;"' in js


def test_js_has_VALID_STATUSES(js):
    assert "VALID_STATUSES" in js


def test_js_uses_escapeHtml_on_title(js):
    assert "escapeHtml(article.title)" in js


def test_js_uses_escapeHtml_on_author(js):
    assert "escapeHtml(article.author" in js


def test_js_uses_escapeHtml_on_body_text(js):
    assert "escapeHtml(p.trim())" in js or "escapeHtml(article.body_text" in js


# ── Pagination guard ──────────────────────────────────────────────────────────

def test_js_has_isLoadingArticles_flag(js):
    assert "isLoadingArticles" in js


def test_js_has_hasMoreArticles_flag(js):
    assert "hasMoreArticles" in js


def test_js_loadArticles_has_finally_block(js):
    assert "finally" in js


def test_js_offset_uses_items_length(js):
    assert "items.length" in js


# ── Topic filter wiring ───────────────────────────────────────────────────────

def test_js_topic_filter_change_listener(js):
    assert "topic-filter" in js
    assert "addEventListener" in js


def test_js_currentTopic_updated_on_change(js):
    assert "currentTopic" in js
    assert "e.target.value" in js


# ── Accessibility ─────────────────────────────────────────────────────────────

def test_html_search_input_has_aria_label(client):
    html = client.get("/").text
    assert 'aria-label="Search articles"' in html
