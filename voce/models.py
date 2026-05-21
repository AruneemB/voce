"""Pure-Python dataclasses mirroring the Voce database schema."""

import sqlite3
from dataclasses import dataclass, fields
from typing import Optional


@dataclass
class Article:
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
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: row[k] for k in row.keys() if k in allowed})


@dataclass
class ReadingState:
    article_id: str
    status: str
    last_played_at: Optional[str]
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ReadingState":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: row[k] for k in row.keys() if k in allowed})


@dataclass
class AudioCache:
    article_id: str
    file_path: str
    voice_id: str
    created_at: str
    last_played_at: str
    duration_sec: Optional[int]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "AudioCache":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: row[k] for k in row.keys() if k in allowed})
