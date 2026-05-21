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
