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


def test_chunk_text_raises_for_non_positive_limit():
    with pytest.raises(ValueError, match="limit must be a positive integer"):
        chunk_text("some text", limit=0)


def test_chunk_text_splits_at_exclamation_boundary():
    text = "A" * 100 + "! " + "B" * 3000
    result = chunk_text(text)
    assert result[0].endswith("! ")
    for chunk in result:
        assert len(chunk) <= ELEVENLABS_CHAR_LIMIT


def test_chunk_text_splits_at_question_boundary():
    text = "A" * 100 + "? " + "B" * 3000
    result = chunk_text(text)
    assert result[0].endswith("? ")
    for chunk in result:
        assert len(chunk) <= ELEVENLABS_CHAR_LIMIT


def test_chunk_text_picks_latest_sentence_boundary_within_limit():
    # ". " at position 100, "! " at position 200 — max() picks the later one
    text = "A" * 100 + ". " + "A" * 98 + "! " + "B" * 3000
    result = chunk_text(text)
    assert result[0].endswith("! ")


def test_chunk_text_produces_no_empty_strings():
    cases = [
        "x" * ELEVENLABS_CHAR_LIMIT,
        "x" * (ELEVENLABS_CHAR_LIMIT * 3),
        "Hello world. " * 300,
        "word " * 600,
    ]
    for text in cases:
        result = chunk_text(text)
        assert all(c for c in result), f"Empty chunk found for input length {len(text)}"


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


@patch("voce.tts.ElevenLabs")
def test_synthesize_article_returns_cached_path_without_calling_elevenlabs(
    mock_elevenlabs_cls, mem_conn_with_article, tmp_path
):
    mp3 = tmp_path / "art1.mp3"
    mp3.write_bytes(b"existing-mp3")
    mem_conn_with_article.execute(
        "INSERT INTO audio_cache (article_id, file_path, voice_id, last_played_at) VALUES (?,?,?,?)",
        ("art1", str(mp3), "voice-test", "2024-01-01T00:00:00Z"),
    )
    mem_conn_with_article.commit()

    out_path = synthesize_article("art1", mem_conn_with_article)

    mock_elevenlabs_cls.assert_not_called()
    assert out_path == mp3
    row = mem_conn_with_article.execute(
        "SELECT last_played_at FROM audio_cache WHERE article_id='art1'"
    ).fetchone()
    assert row["last_played_at"] != "2024-01-01T00:00:00Z"


@patch("voce.tts.ElevenLabs")
def test_synthesize_article_resynthesize_when_cached_file_missing(
    mock_elevenlabs_cls, mem_conn_with_article, tmp_path
):
    stale_path = tmp_path / "stale-art1.mp3"
    # Do NOT write the file — simulate a missing MP3
    mem_conn_with_article.execute(
        "INSERT INTO audio_cache (article_id, file_path, voice_id, last_played_at) VALUES (?,?,?,?)",
        ("art1", str(stale_path), "voice-test", "2020-01-01T00:00:00Z"),
    )
    mem_conn_with_article.commit()

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

    mock_elevenlabs_cls.assert_called_once()
    assert out_path.exists()
    row = mem_conn_with_article.execute(
        "SELECT file_path FROM audio_cache WHERE article_id='art1'"
    ).fetchone()
    assert row is not None
    assert row["file_path"] == str(out_path)
