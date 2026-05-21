"""FastAPI application factory, routes, and response models for Voce."""

from typing import Optional

from pydantic import BaseModel

SECTION_LABELS: dict[str, str] = {
    "physics": "Physics",
    "mathematics": "Mathematics",
    "biology": "Biology",
    "computer-science": "Computer Science",
}


class SectionOut(BaseModel):
    section: str
    display_name: str
    unread_count: int


class ArticleSummaryOut(BaseModel):
    id: str
    section: str
    title: str
    author: Optional[str]
    published_at: str
    url: str
    summary: Optional[str]
    status: str
    quanta_audio_url: Optional[str]


class ArticleDetailOut(ArticleSummaryOut):
    body_text: str


class PaginatedArticles(BaseModel):
    items: list[ArticleSummaryOut]
    total: int
    limit: int
    offset: int


class TopicOut(BaseModel):
    slug: str
    label: str
    article_count: int
