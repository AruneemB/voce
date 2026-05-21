"""FastAPI application factory, routes, and response models for Voce."""

import sqlite3
from contextlib import asynccontextmanager
from typing import Annotated, Optional

import asyncio

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, Response

from voce.config import settings
from voce.db import bootstrap_schema, get_connection
from voce.feeds import refresh_all_feeds

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


@app.get("/")
def root() -> FileResponse:
    return FileResponse("voce/static/index.html")


@app.get("/api/sections", response_model=list[SectionOut])
def list_sections(conn: ConnDep) -> list[SectionOut]:
    rows = conn.execute(
        "SELECT a.section, COUNT(*) AS unread_count "
        "FROM articles a "
        "JOIN reading_state rs ON rs.article_id = a.id "
        "WHERE rs.status = 'unread' "
        "GROUP BY a.section"
    ).fetchall()
    counts: dict[str, int] = {r["section"]: r["unread_count"] for r in rows}
    return [
        SectionOut(section=slug, display_name=label, unread_count=counts.get(slug, 0))
        for slug, label in SECTION_LABELS.items()
    ]


@app.get("/api/articles", response_model=PaginatedArticles)
def list_articles(
    conn: ConnDep,
    section: Optional[str] = Query(None),
    topic: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> PaginatedArticles:
    conditions: list[tuple[str, object]] = []
    if section:
        conditions.append(("a.section = ?", section))
    if status:
        conditions.append(("rs.status = ?", status))
    if topic:
        conditions.append((
            "EXISTS (SELECT 1 FROM article_topics at WHERE at.article_id = a.id AND at.topic = ?)",
            topic,
        ))

    base_cols = (
        "SELECT a.id, a.section, a.title, a.author, a.published_at, a.url, "
        "a.summary, a.quanta_audio_url, COALESCE(rs.status, 'unread') AS status "
    )
    base_from = (
        "FROM articles a "
        "LEFT JOIN reading_state rs ON rs.article_id = a.id"
    )
    count_from = (
        "SELECT COUNT(*) "
        "FROM articles a "
        "LEFT JOIN reading_state rs ON rs.article_id = a.id"
    )

    fts_param: list[object] = []
    if q:
        fts_join = (
            " JOIN (SELECT rowid FROM fts_articles WHERE fts_articles MATCH ?) fts"
            " ON fts.rowid = a.rowid"
        )
        base_from = base_from + fts_join
        count_from = count_from + fts_join
        fts_param = [q]

    where_clause = ""
    where_params: list[object] = []
    if conditions:
        where_clause = " WHERE " + " AND ".join(c[0] for c in conditions)
        where_params = [c[1] for c in conditions]

    order_limit = " ORDER BY a.published_at DESC LIMIT ? OFFSET ?"

    data_sql = base_cols + base_from + where_clause + order_limit
    count_sql = count_from + where_clause

    data_params = fts_param + where_params + [limit, offset]
    count_params = fts_param + where_params

    rows = conn.execute(data_sql, data_params).fetchall()
    total = conn.execute(count_sql, count_params).fetchone()[0]

    items = [
        ArticleSummaryOut(
            id=r["id"],
            section=r["section"],
            title=r["title"],
            author=r["author"],
            published_at=r["published_at"],
            url=r["url"],
            summary=r["summary"],
            status=r["status"],
            quanta_audio_url=r["quanta_audio_url"],
        )
        for r in rows
    ]
    return PaginatedArticles(items=items, total=total, limit=limit, offset=offset)


@app.get("/api/articles/{article_id}", response_model=ArticleDetailOut)
def get_article(article_id: str, conn: ConnDep) -> ArticleDetailOut:
    row = conn.execute(
        "SELECT a.id, a.section, a.title, a.author, a.published_at, a.url, "
        "a.summary, a.quanta_audio_url, a.body_text, COALESCE(rs.status, 'unread') AS status "
        "FROM articles a "
        "LEFT JOIN reading_state rs ON rs.article_id = a.id "
        "WHERE a.id = ?",
        (article_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return ArticleDetailOut(
        id=row["id"],
        section=row["section"],
        title=row["title"],
        author=row["author"],
        published_at=row["published_at"],
        url=row["url"],
        summary=row["summary"],
        status=row["status"],
        quanta_audio_url=row["quanta_audio_url"],
        body_text=row["body_text"],
    )


@app.get("/api/topics", response_model=list[TopicOut])
def list_topics(
    conn: ConnDep,
    section: Optional[str] = Query(None),
) -> list[TopicOut]:
    if section:
        rows = conn.execute(
            "SELECT at.topic AS slug, COUNT(*) AS article_count "
            "FROM article_topics at "
            "JOIN articles a ON a.id = at.article_id "
            "WHERE a.section = ? "
            "GROUP BY at.topic "
            "ORDER BY at.topic",
            (section,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT topic AS slug, COUNT(*) AS article_count "
            "FROM article_topics "
            "GROUP BY topic "
            "ORDER BY topic"
        ).fetchall()
    return [
        TopicOut(
            slug=r["slug"],
            label=r["slug"].replace("-", " ").title(),
            article_count=r["article_count"],
        )
        for r in rows
    ]


@app.post("/api/refresh")
async def refresh(conn: ConnDep) -> dict:
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(None, refresh_all_feeds, conn)
    return {slug: list(counts) for slug, counts in results.items()}
