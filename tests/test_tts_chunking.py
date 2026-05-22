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
