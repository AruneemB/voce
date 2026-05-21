"""Tests for voce.article — all run offline via mocks and in-memory SQLite."""

import sqlite3
from unittest.mock import MagicMock, patch

import httpx
import pytest

from voce.db import bootstrap_schema
from voce.exceptions import ArticleFetchError
from voce.article import (
    apply_latex_substitutions,
    build_preamble,
    clean_html_for_tts,
    count_words,
    enrich_all_unenriched,
    enrich_article,
    fetch_article_html,
)

@pytest.fixture
def mem_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def article_row(mem_conn):
    mem_conn.execute(
        "INSERT INTO articles (id, section, title, author, published_at, url, body_html, body_text)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            "art001", "physics", "The Shape of Reality", "Jane Smith",
            "2024-03-15T09:00:00Z", "https://example.com/", "", "",
        ),
    )
    mem_conn.commit()
    return mem_conn


@pytest.fixture
def mock_client():
    return MagicMock(spec=httpx.Client)


LATEX_CASES = [
    (r"\frac{1}{2}", "1 over 2"),
    (r"\sqrt{x}", "the square root of x"),
    (r"\infty", "infinity"),
    (r"\pi", "pi"),
    (r"\alpha", "alpha"),
    (r"\sum", "sum"),
    (r"\int", "integral"),
]


@pytest.mark.parametrize("inp,expected_substr", LATEX_CASES)
def test_apply_latex_substitutions(inp, expected_substr):
    result = apply_latex_substitutions(inp)
    assert expected_substr in result, f"Expected '{expected_substr}' in '{result}'"


def test_clean_html_simple_paragraph():
    result = clean_html_for_tts("<p>Hello world.</p>")
    assert result == "Hello world."


def test_clean_html_strips_script_tags():
    result = clean_html_for_tts("<p>Keep this</p><script>alert('x')</script>")
    assert "alert" not in result
    assert "Keep this" in result


def test_clean_html_empty_input():
    result = clean_html_for_tts("")
    assert result == ""


def test_clean_html_blockquote():
    result = clean_html_for_tts("<blockquote>Important thought.</blockquote>")
    assert "Quote:" in result
    assert "End quote." in result


def test_clean_html_ordered_list():
    result = clean_html_for_tts("<ol><li>Alpha</li><li>Beta</li><li>Gamma</li></ol>")
    assert "First" in result
    assert "Second" in result
    assert "Third" in result


def test_count_words_empty():
    assert count_words("") == 0


def test_count_words_normal():
    assert count_words("Hello world foo") == 3


def test_build_preamble_includes_title_and_author():
    result = build_preamble("The Shape of Space", "Ada Lovelace", "2024-03-15T12:00:00Z")
    assert "The Shape of Space" in result
    assert "Ada Lovelace" in result
    assert "2024-03-15" in result
    assert result.startswith("From Quanta Magazine.")


# ---------------------------------------------------------------------------
# Extended clean_html_for_tts — class filter
# ---------------------------------------------------------------------------

def test_clean_removes_share_class():
    html = '<div class="share-buttons">Share this</div><p>Read me</p>'
    result = clean_html_for_tts(html)
    assert "Share this" not in result
    assert "Read me" in result


def test_clean_removes_newsletter_class():
    html = '<section class="newsletter-signup">Subscribe</section><p>Article</p>'
    result = clean_html_for_tts(html)
    assert "Subscribe" not in result
    assert "Article" in result


def test_clean_removes_related_class():
    html = '<div class="related-articles">Related</div><p>Content</p>'
    result = clean_html_for_tts(html)
    assert "Related" not in result
    assert "Content" in result


def test_clean_removes_byline_class():
    html = '<p class="byline">By Author Name</p><p>Article text</p>'
    result = clean_html_for_tts(html)
    assert "By Author Name" not in result
    assert "Article text" in result


def test_clean_removes_sidebar_class():
    html = '<div class="sidebar">Side content</div><p>Main content</p>'
    result = clean_html_for_tts(html)
    assert "Side content" not in result
    assert "Main content" in result


def test_clean_class_filter_case_insensitive():
    html = '<div class="Share-Widget">X</div><p>Y</p>'
    result = clean_html_for_tts(html)
    assert "X" not in result
    assert "Y" in result


# ---------------------------------------------------------------------------
# Extended clean_html_for_tts — structural tags
# ---------------------------------------------------------------------------

def test_clean_removes_aside():
    html = "<p>Main</p><aside>Sidebar content</aside>"
    result = clean_html_for_tts(html)
    assert "Sidebar content" not in result
    assert "Main" in result


def test_clean_removes_figure():
    html = "<p>Intro</p><figure><img src='x.jpg'><figcaption>caption</figcaption></figure>"
    result = clean_html_for_tts(html)
    assert "caption" not in result
    assert "Intro" in result


def test_clean_removes_style():
    html = "<style>.foo{color:red}</style><p>visible</p>"
    result = clean_html_for_tts(html)
    assert "color" not in result
    assert "visible" in result


def test_clean_heading_adds_period():
    html = "<h2>Dark Matter</h2><p>body</p>"
    result = clean_html_for_tts(html)
    assert "Dark Matter." in result


def test_clean_heading_all_levels():
    for level in range(1, 7):
        html = f"<h{level}>Heading {level}</h{level}>"
        result = clean_html_for_tts(html)
        assert f"Heading {level}." in result


def test_clean_br_preserved_as_whitespace():
    html = "<p>line one<br>line two</p>"
    result = clean_html_for_tts(html)
    assert "line one" in result
    assert "line two" in result


# ---------------------------------------------------------------------------
# Extended clean_html_for_tts — ordered lists
# ---------------------------------------------------------------------------

def test_clean_ol_single_item():
    html = "<ol><li>Only item</li></ol>"
    result = clean_html_for_tts(html)
    assert "First," in result
    assert "Only item" in result


def test_clean_ol_tenth_item_uses_number():
    items = "".join(f"<li>Item{i}</li>" for i in range(1, 11))
    html = f"<ol>{items}</ol>"
    result = clean_html_for_tts(html)
    assert "10." in result


# ---------------------------------------------------------------------------
# Extended clean_html_for_tts — unordered lists
# ---------------------------------------------------------------------------

def test_clean_ul_oxford_comma():
    html = "<ul><li>A</li><li>B</li><li>C</li></ul>"
    result = clean_html_for_tts(html)
    assert "A, B, and C" in result


def test_clean_ul_two_items():
    html = "<ul><li>X</li><li>Y</li></ul>"
    result = clean_html_for_tts(html)
    assert "X" in result
    assert "Y" in result
    assert "and" in result


def test_clean_ul_single_item():
    html = "<ul><li>Only</li></ul>"
    result = clean_html_for_tts(html)
    assert "Only" in result


# ---------------------------------------------------------------------------
# Extended clean_html_for_tts — LaTeX passthrough and whitespace
# ---------------------------------------------------------------------------

def test_clean_latex_in_html():
    html = r"<p>The equation \frac{1}{2} appears here.</p>"
    result = clean_html_for_tts(html)
    assert "1 over 2" in result


def test_clean_no_literal_backslashes_after_latex():
    html = r"<p>Consider \alpha and \beta in the proof.</p>"
    result = clean_html_for_tts(html)
    assert "\\" not in result


def test_clean_no_html_tags_in_output():
    html = "<article><h1>Title</h1><p>Body <strong>bold</strong> text.</p></article>"
    result = clean_html_for_tts(html)
    assert "<" not in result
    assert ">" not in result


def test_clean_whitespace_normalized():
    html = "<p>Many    spaces here</p>"
    result = clean_html_for_tts(html)
    assert "  " not in result


# ---------------------------------------------------------------------------
# Additional count_words and build_preamble coverage
# ---------------------------------------------------------------------------

def test_count_words_extra_whitespace():
    assert count_words("  hello   world  ") == 2


def test_count_words_newlines():
    assert count_words("one\ntwo\nthree") == 3


def test_build_preamble_none_author():
    result = build_preamble("Black Holes", None, "2024-03-15T09:00:00Z")
    assert "By Quanta Magazine." in result


def test_build_preamble_empty_author():
    result = build_preamble("Title", "", "2024-01-01T00:00:00Z")
    assert "By Quanta Magazine." in result


def test_build_preamble_date_sliced():
    result = build_preamble("T", "A", "2024-11-30T00:00:00Z")
    assert "2024-11-30" in result
    assert "T00:00:00Z" not in result


def test_build_preamble_exact_format():
    result = build_preamble("Black Holes", "Jane Smith", "2024-03-15T09:00:00Z")
    assert result == "From Quanta Magazine. Black Holes. By Jane Smith. Published 2024-03-15."


# ---------------------------------------------------------------------------
# fetch_article_html
# ---------------------------------------------------------------------------

def test_fetch_article_html_success(mock_client):
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.text = "<html><body><p>Article content</p></body></html>"
    mock_client.get.return_value = mock_response

    result = fetch_article_html("https://example.com/article", mock_client)
    assert result == "<html><body><p>Article content</p></body></html>"


def test_fetch_article_html_sends_user_agent(mock_client):
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.text = "<p>content</p>"
    mock_client.get.return_value = mock_response

    fetch_article_html("https://example.com/article", mock_client)

    headers = mock_client.get.call_args.kwargs.get("headers", {})
    assert "Voce/0.1" in headers.get("User-Agent", "")


def test_fetch_article_html_timeout_raises(mock_client):
    mock_client.get.side_effect = httpx.TimeoutException("timed out")

    with pytest.raises(ArticleFetchError) as exc_info:
        fetch_article_html("https://example.com/article", mock_client)
    assert exc_info.value.url == "https://example.com/article"


def test_fetch_article_html_404_raises(mock_client):
    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 404
    mock_client.get.return_value = mock_response

    with pytest.raises(ArticleFetchError):
        fetch_article_html("https://example.com/404", mock_client)


def test_fetch_article_html_500_raises(mock_client):
    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 500
    mock_client.get.return_value = mock_response

    with pytest.raises(ArticleFetchError):
        fetch_article_html("https://example.com/500", mock_client)


def test_fetch_article_html_connect_error_raises(mock_client):
    mock_client.get.side_effect = httpx.ConnectError("connection refused")

    with pytest.raises(ArticleFetchError) as exc_info:
        fetch_article_html("https://example.com/article", mock_client)
    assert exc_info.value.url == "https://example.com/article"


def test_fetch_article_html_read_error_raises(mock_client):
    mock_client.get.side_effect = httpx.ReadError("connection reset")

    with pytest.raises(ArticleFetchError):
        fetch_article_html("https://example.com/article", mock_client)


def test_enrich_article_returns_false_on_connect_error(article_row, mock_client):
    mock_client.get.side_effect = httpx.ConnectError("refused")

    ok = enrich_article("art001", "https://example.com/", "", article_row, mock_client)
    assert ok is False


# ---------------------------------------------------------------------------
# enrich_article
# ---------------------------------------------------------------------------

def test_enrich_article_with_body_html_does_not_fetch(article_row, mock_client):
    ok = enrich_article(
        "art001", "https://example.com/",
        "<p>Interesting physics.</p>", article_row, mock_client,
    )
    assert ok is True
    mock_client.get.assert_not_called()

    row = article_row.execute(
        "SELECT body_text FROM articles WHERE id='art001'"
    ).fetchone()
    assert "Interesting physics." in row["body_text"]
    assert "From Quanta Magazine." in row["body_text"]


def test_enrich_article_empty_body_html_triggers_fetch(article_row, mock_client):
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.text = "<p>Fetched content.</p>"
    mock_client.get.return_value = mock_response

    ok = enrich_article("art001", "https://example.com/", "", article_row, mock_client)
    assert ok is True
    mock_client.get.assert_called_once()


def test_enrich_article_fetch_error_returns_false(article_row, mock_client):
    mock_client.get.side_effect = httpx.TimeoutException("timeout")

    ok = enrich_article("art001", "https://example.com/", "", article_row, mock_client)
    assert ok is False


def test_enrich_article_prepends_preamble(article_row, mock_client):
    ok = enrich_article(
        "art001", "https://example.com/",
        "<p>Body text.</p>", article_row, mock_client,
    )
    assert ok is True
    row = article_row.execute(
        "SELECT body_text FROM articles WHERE id='art001'"
    ).fetchone()
    body = row["body_text"]
    assert body.startswith("From Quanta Magazine.")
    assert "The Shape of Reality" in body
    assert "Jane Smith" in body
    assert "2024-03-15" in body


def test_enrich_article_fetch_error_logs_warning(article_row, mock_client):
    mock_client.get.side_effect = httpx.TimeoutException("boom")

    with patch("voce.article.logger") as mock_logger:
        ok = enrich_article("art001", "https://example.com/", "", article_row, mock_client)

    assert ok is False
    mock_logger.warning.assert_called_once()


def test_enrich_article_stores_fetched_html(article_row, mock_client):
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.text = "<p>Fetched body.</p>"
    mock_client.get.return_value = mock_response

    enrich_article("art001", "https://example.com/", "", article_row, mock_client)

    row = article_row.execute(
        "SELECT body_html FROM articles WHERE id='art001'"
    ).fetchone()
    assert row["body_html"] == "<p>Fetched body.</p>"


def test_enrich_article_missing_id_returns_false(mem_conn, mock_client):
    ok = enrich_article(
        "nonexistent", "https://example.com/",
        "<p>Text.</p>", mem_conn, mock_client,
    )
    assert ok is False


def test_enrich_article_missing_id_logs_warning(mem_conn, mock_client):
    with patch("voce.article.logger") as mock_logger:
        ok = enrich_article(
            "nonexistent", "https://example.com/",
            "<p>Text.</p>", mem_conn, mock_client,
        )
    assert ok is False
    mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# enrich_all_unenriched
# ---------------------------------------------------------------------------

def _insert_article(conn, article_id, body_html="", body_text=""):
    conn.execute(
        "INSERT INTO articles (id, section, title, author, published_at, url, body_html, body_text)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            article_id, "physics", f"Title {article_id}", "Author",
            "2024-01-01T00:00:00Z", f"https://example.com/{article_id}",
            body_html, body_text,
        ),
    )
    conn.commit()


def test_enrich_all_unenriched_success(mem_conn, mock_client):
    _insert_article(mem_conn, "a1", body_html="<p>content</p>")
    _insert_article(mem_conn, "a2", body_html="<p>other</p>")

    success, failure = enrich_all_unenriched(mem_conn, mock_client)
    assert success == 2
    assert failure == 0


def test_enrich_all_unenriched_skips_enriched(mem_conn, mock_client):
    _insert_article(mem_conn, "a3", body_html="<p>x</p>", body_text="Already enriched text")
    _insert_article(mem_conn, "a4", body_html="<p>y</p>")

    success, failure = enrich_all_unenriched(mem_conn, mock_client)
    assert success == 1
    assert failure == 0


def test_enrich_all_unenriched_counts_failures(mem_conn, mock_client):
    _insert_article(mem_conn, "b1", body_html="", body_text="")
    _insert_article(mem_conn, "b2", body_html="<p>good</p>")
    mock_client.get.side_effect = httpx.TimeoutException("timeout")

    success, failure = enrich_all_unenriched(mem_conn, mock_client)
    assert success == 1
    assert failure == 1


def test_enrich_all_unenriched_empty_db(mem_conn, mock_client):
    success, failure = enrich_all_unenriched(mem_conn, mock_client)
    assert success == 0
    assert failure == 0
    mock_client.get.assert_not_called()


def test_enrich_all_unenriched_updates_body_text(mem_conn, mock_client):
    _insert_article(mem_conn, "c1", body_html="<p>Clean this.</p>")

    enrich_all_unenriched(mem_conn, mock_client)

    row = mem_conn.execute(
        "SELECT body_text FROM articles WHERE id='c1'"
    ).fetchone()
    assert row["body_text"] != ""
    assert "From Quanta Magazine." in row["body_text"]
    assert "Clean this." in row["body_text"]
