"""Pure-Python dataclasses mirroring the Voce database schema."""

import sqlite3
from dataclasses import dataclass, fields
from typing import Optional


@dataclass
class Article:
    """Ingested Quanta Magazine article with metadata, HTML source, and plain-text body."""

    id: str
    section: str
    title: str
    author: Optional[str]
    published_at: str
    url: str
    summary: Optional[str]
    body_html: str
    body_text: str
    quanta_audio_url: Optional[str]
    ingested_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Article":
        """Hydrate an Article from a sqlite3.Row, ignoring any extra columns."""
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: row[k] for k in row.keys() if k in allowed})


@dataclass
class ReadingState:
    """Per-article playback status and timestamps."""

    article_id: str
    status: str
    last_played_at: Optional[str]
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ReadingState":
        """Hydrate a ReadingState from a sqlite3.Row, ignoring any extra columns."""
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: row[k] for k in row.keys() if k in allowed})


@dataclass
class AudioCache:
    """Metadata for a locally synthesised MP3 file linked to an article."""

    article_id: str
    file_path: str
    voice_id: str
    created_at: str
    last_played_at: str
    duration_sec: Optional[int]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "AudioCache":
        """Hydrate an AudioCache from a sqlite3.Row, ignoring any extra columns."""
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: row[k] for k in row.keys() if k in allowed})
