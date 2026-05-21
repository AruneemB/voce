"""FastAPI application factory, routes, and response models for Voce."""

import sqlite3
from contextlib import asynccontextmanager
from typing import Annotated, Optional

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, Response

from voce.config import settings
from voce.db import bootstrap_schema, get_connection

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


def get_conn() -> sqlite3.Connection:  # type: ignore[return]
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


ConnDep = Annotated[sqlite3.Connection, Depends(get_conn)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_connection()
    bootstrap_schema(conn)
    conn.close()
    logger.info("Voce schema bootstrapped")
    yield


def create_app() -> FastAPI:
    _app = FastAPI(title="Voce", lifespan=lifespan)
    _app.add_middleware(LocalhostOnlyMiddleware)
    _app.mount("/static", StaticFiles(directory="voce/static"), name="static")
    return _app


app = create_app()
