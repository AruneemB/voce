"""ElevenLabs TTS synthesis, chunk splitting, and MP3 assembly."""

from __future__ import annotations

import sqlite3
from io import BytesIO
from pathlib import Path

from loguru import logger
from mutagen.mp3 import MP3

from elevenlabs import ElevenLabs

from voce.article import build_preamble
from voce.config import settings
from voce.exceptions import ArticleNotFoundError, ArticleTextMissingError, TTSSynthesisError

ELEVENLABS_CHAR_LIMIT: int = 2500


def chunk_text(text: str, limit: int = ELEVENLABS_CHAR_LIMIT) -> list[str]:
    """Split *text* into chunks each no longer than *limit* characters.

    Splitting preference order: sentence boundary (`. `, `! `, `? `), then
    the last space within the limit, then a hard character-count split as a
    last resort (which may split inside a long token).  Empty strings are
    filtered from the result.

    Raises ValueError if *limit* is not a positive integer.
    """
    if limit <= 0:
        raise ValueError(f"limit must be a positive integer, got {limit}")
    if len(text) <= limit:
        return [text]
    p = max(
        text.rfind('. ', 0, limit),
        text.rfind('! ', 0, limit),
        text.rfind('? ', 0, limit),
    )
    if p != -1:
        split_at = p + 2
    else:
        p = text.rfind(' ', 0, limit)
        split_at = p + 1 if p != -1 else limit
    first = text[:split_at]
    rest = chunk_text(text[split_at:], limit)
    return [c for c in [first] + rest if c]


def synthesize_chunk(text: str, client: ElevenLabs) -> bytes:
    """Synthesise *text* to MP3 bytes using the given ElevenLabs *client*.

    Uses ``settings.elevenlabs_voice_id``, ``settings.elevenlabs_model_id``,
    and the ``mp3_44100_128`` output format.  Raises ``TTSSynthesisError`` on
    any ElevenLabs SDK exception.
    """
    try:
        return b"".join(client.text_to_speech.convert(
            voice_id=settings.elevenlabs_voice_id,
            text=text,
            model_id=settings.elevenlabs_model_id,
            output_format="mp3_44100_128",
        ))
    except Exception as exc:
        raise TTSSynthesisError(article_id="unknown", cause=exc) from exc


def get_audio_duration(mp3_bytes: bytes) -> float:
    """Return the duration in seconds of the MP3 audio in *mp3_bytes*."""
    audio = MP3(BytesIO(mp3_bytes))
    return audio.info.length


def synthesize_article(article_id: str, conn: sqlite3.Connection) -> Path:
    """Synthesise the article identified by *article_id* and return the MP3 path.

    Pipeline:
    1. Look up the article; raise ``ArticleNotFoundError`` if absent or
       ``ArticleTextMissingError`` if ``body_text`` is empty.
    2. Return the cached path immediately if an ``audio_cache`` row exists and
       the MP3 file is present on disk (updating ``last_played_at``).  If the
       row exists but the file is gone, the stale row is deleted and synthesis
       proceeds.
    3. Build the full narration text and enforce the 50,000-character cost guard.
    4. Chunk, synthesise via ElevenLabs, concatenate, write to disk, and insert
       the ``audio_cache`` row.
    """
    row = conn.execute(
        "SELECT id, title, author, published_at, body_text FROM articles WHERE id=?",
        (article_id,),
    ).fetchone()
    if row is None:
        raise ArticleNotFoundError(article_id)
    if not row["body_text"]:
        raise ArticleTextMissingError(article_id)

    cache_row = conn.execute(
        "SELECT file_path, last_played_at FROM audio_cache WHERE article_id=?",
        (article_id,),
    ).fetchone()
    if cache_row is not None:
        cached_path = Path(cache_row["file_path"])
        if cached_path.exists():
            conn.execute(
                "UPDATE audio_cache SET last_played_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE article_id=?",
                (article_id,),
            )
            conn.commit()
            return cached_path
        logger.warning("Cached MP3 for article {} is missing from disk; re-synthesising", article_id)
        conn.execute("DELETE FROM audio_cache WHERE article_id=?", (article_id,))
        conn.commit()

    full_text = build_preamble(row["title"], row["author"], row["published_at"]) + "\n\n" + row["body_text"]
    if len(full_text) > 50_000:
        logger.warning(
            "Article {} text exceeds 50,000 chars ({}); refusing synthesis",
            article_id,
            len(full_text),
        )
        raise ArticleTextMissingError(article_id)

    chunks = chunk_text(full_text)

    client = ElevenLabs(api_key=settings.elevenlabs_api_key)

    try:
        mp3_chunks = [synthesize_chunk(c, client) for c in chunks]
    except TTSSynthesisError:
        logger.error("TTS synthesis failed for article {}", article_id)
        raise

    mp3_bytes = b"".join(mp3_chunks)
    duration = get_audio_duration(mp3_bytes)

    out_path = settings.audio_cache_dir / f"{article_id}.mp3"
    settings.audio_cache_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(mp3_bytes)

    conn.execute(
        "INSERT OR REPLACE INTO audio_cache (article_id, file_path, voice_id, duration_sec) VALUES (?,?,?,?)",
        (article_id, str(out_path), settings.elevenlabs_voice_id, int(duration)),
    )
    conn.commit()
    return out_path
