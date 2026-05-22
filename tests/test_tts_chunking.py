import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from voce.db import bootstrap_schema
from voce.exceptions import ArticleNotFoundError, ArticleTextMissingError
from voce.tts import ELEVENLABS_CHAR_LIMIT, chunk_text, synthesize_article


# ── chunk_text tests ──────────────────────────────────────────────────────────

def test_chunk_text_short_returns_single_chunk():
    text = "Short text."
    result = chunk_text(text)
    assert result == ["Short text."]


def test_chunk_text_exactly_at_limit_returns_single_chunk():
    text = "x" * ELEVENLABS_CHAR_LIMIT
    result = chunk_text(text)
    assert len(result) == 1
    assert len(result[0]) == ELEVENLABS_CHAR_LIMIT


def test_chunk_text_splits_at_sentence_boundary():
    sentence = "A" * 100 + ". "
    text = sentence * 30  # ~3060 chars, needs splitting
    result = chunk_text(text)
    assert len(result) > 1
    for chunk in result:
        assert len(chunk) <= ELEVENLABS_CHAR_LIMIT


def test_chunk_text_splits_at_space_when_no_sentence_boundary():
    # A single long "word" interspersed with spaces but no sentence-ending punctuation
    text = ("word " * 600).strip()  # 3000 chars, no periods
    result = chunk_text(text)
    assert len(result) > 1
    for chunk in result:
        assert len(chunk) <= ELEVENLABS_CHAR_LIMIT


def test_chunk_text_hard_splits_when_no_space():
    text = "x" * (ELEVENLABS_CHAR_LIMIT * 2)
    result = chunk_text(text)
    assert len(result) == 2
    for chunk in result:
        assert len(chunk) <= ELEVENLABS_CHAR_LIMIT


# ── synthesize_article tests ──────────────────────────────────────────────────

@pytest.fixture
def mem_conn_with_article():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_schema(conn)
    conn.execute(
        "INSERT INTO articles (id, section, title, author, published_at, url, body_html, body_text) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("art1", "physics", "Test", "Author", "2024-01-01T00:00:00Z", "https://x.com/1", "", "Hello world."),
    )
    conn.commit()
    yield conn
    conn.close()


def test_synthesize_article_raises_for_missing_article(mem_conn_with_article):
    with pytest.raises(ArticleNotFoundError):
        synthesize_article("nonexistent", mem_conn_with_article)


def test_synthesize_article_raises_for_empty_body_text(mem_conn_with_article):
    mem_conn_with_article.execute("UPDATE articles SET body_text='' WHERE id='art1'")
    mem_conn_with_article.commit()
    with pytest.raises(ArticleTextMissingError):
        synthesize_article("art1", mem_conn_with_article)


@patch("voce.tts.ElevenLabs")
def test_synthesize_article_writes_file_and_inserts_cache(mock_elevenlabs_cls, mem_conn_with_article, tmp_path):
    mock_client = MagicMock()
    mock_client.text_to_speech.convert.return_value = iter([b"\xff\xfb" + b"\x00" * 100])
    mock_elevenlabs_cls.return_value = mock_client

    from voce import config as cfg
    original_dir = cfg.settings.audio_cache_dir
    cfg.settings.audio_cache_dir = tmp_path

    try:
        with patch("voce.tts.get_audio_duration", return_value=5.0):
            out_path = synthesize_article("art1", mem_conn_with_article)
    finally:
        cfg.settings.audio_cache_dir = original_dir

    assert out_path.exists()
    row = mem_conn_with_article.execute(
        "SELECT * FROM audio_cache WHERE article_id='art1'"
    ).fetchone()
    assert row is not None
