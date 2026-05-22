"""ElevenLabs TTS synthesis, chunk splitting, and MP3 assembly."""

from __future__ import annotations

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
