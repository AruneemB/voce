"""FastAPI application factory, routes, and response models for Voce."""

from typing import Optional

from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from voce.config import settings

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


class LocalhostOnlyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        host_header = request.headers.get("host", "")
        allowed = {
            f"127.0.0.1:{settings.port}",
            f"localhost:{settings.port}",
        }
        if host_header not in allowed:
            return Response("Forbidden: remote access not allowed", status_code=403)
        return await call_next(request)
