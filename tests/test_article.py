"""Tests for voce.article — all run offline via mocks and in-memory SQLite."""

import pytest

from voce.article import apply_latex_substitutions, clean_html_for_tts, count_words, build_preamble

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
