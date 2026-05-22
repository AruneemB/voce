"""ElevenLabs TTS synthesis, chunk splitting, and MP3 assembly."""

from __future__ import annotations

from io import BytesIO

from loguru import logger
from mutagen.mp3 import MP3

from voce.config import settings
from voce.exceptions import TTSSynthesisError

ELEVENLABS_CHAR_LIMIT: int = 2500


def chunk_text(text: str, limit: int = ELEVENLABS_CHAR_LIMIT) -> list[str]:
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


def synthesize_chunk(text: str, client) -> bytes:
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
    audio = MP3(BytesIO(mp3_bytes))
    return audio.info.length
