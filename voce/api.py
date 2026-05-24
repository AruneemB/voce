"""FastAPI application factory, routes, and response models for Voce."""

import asyncio
import ipaddress
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Optional

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
from voce.tts import synthesize_article

_synthesis_in_progress: set[str] = set()

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


class AudioStatusOut(BaseModel):
    cached: bool
    url: Optional[str]
    duration_sec: Optional[int]
    pending: bool


class LocalhostOnlyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Primary: reject connections from non-loopback IPs (not spoofable via headers).
        # Non-IP client identifiers (e.g. the test-client sentinel) are skipped.
        if request.client:
            try:
                ip = ipaddress.ip_address(request.client.host)
                if not ip.is_loopback:
                    return Response("Forbidden: remote access not allowed", status_code=403)
            except ValueError:
                pass
        # Secondary: validate the Host header to defend against DNS-rebinding.
        host_header = request.headers.get("host", "")
        if host_header not in {f"127.0.0.1:{settings.port}", f"localhost:{settings.port}"}:
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
    settings.audio_cache_dir.mkdir(parents=True, exist_ok=True)
    _app.mount("/audio", StaticFiles(directory=str(settings.audio_cache_dir)), name="audio")
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
        "LEFT JOIN reading_state rs ON rs.article_id = a.id "
        "WHERE COALESCE(rs.status, 'unread') = 'unread' "
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
        conditions.append(("COALESCE(rs.status, 'unread') = ?", status))
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


@app.post("/api/articles/{article_id}/audio", status_code=202)
async def trigger_audio(article_id: str, conn: ConnDep) -> dict:
    if article_id in _synthesis_in_progress:
        return {"status": "pending"}
    cache_row = conn.execute(
        "SELECT file_path FROM audio_cache WHERE article_id=?", (article_id,)
    ).fetchone()
    if cache_row:
        if Path(cache_row["file_path"]).exists():
            return {"status": "ready", "url": f"/api/articles/{article_id}/audio/stream"}
        conn.execute("DELETE FROM audio_cache WHERE article_id=?", (article_id,))
        conn.commit()
    article_row = conn.execute(
        "SELECT 1 FROM articles WHERE id=?", (article_id,)
    ).fetchone()
    if article_row is None:
        raise HTTPException(status_code=404, detail="Article not found")
    _synthesis_in_progress.add(article_id)

    def _run() -> None:
        synth_conn = None
        try:
            synth_conn = get_connection()
            synthesize_article(article_id, synth_conn)
        except Exception:
            logger.exception("Background synthesis failed for article {}", article_id)
        finally:
            if synth_conn is not None:
                synth_conn.close()
            _synthesis_in_progress.discard(article_id)

    asyncio.get_event_loop().run_in_executor(None, _run)
    return {"status": "pending"}


@app.get("/api/articles/{article_id}/audio/status", response_model=AudioStatusOut)
def get_audio_status(article_id: str, conn: ConnDep) -> AudioStatusOut:
    row = conn.execute(
        "SELECT file_path, duration_sec FROM audio_cache WHERE article_id=?",
        (article_id,),
    ).fetchone()
    if row:
        if Path(row["file_path"]).exists():
            return AudioStatusOut(
                cached=True,
                url=f"/api/articles/{article_id}/audio/stream",
                duration_sec=row["duration_sec"],
                pending=article_id in _synthesis_in_progress,
            )
        conn.execute("DELETE FROM audio_cache WHERE article_id=?", (article_id,))
        conn.commit()
    return AudioStatusOut(
        cached=False,
        url=None,
        duration_sec=None,
        pending=article_id in _synthesis_in_progress,
    )


@app.get("/api/articles/{article_id}/audio/stream")
def stream_audio(article_id: str, conn: ConnDep) -> FileResponse:
    row = conn.execute(
        "SELECT file_path, duration_sec FROM audio_cache WHERE article_id=?",
        (article_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Audio not found")
    if not Path(row["file_path"]).exists():
        conn.execute("DELETE FROM audio_cache WHERE article_id=?", (article_id,))
        conn.commit()
        raise HTTPException(status_code=404, detail="Audio file missing")
    conn.execute(
        "UPDATE audio_cache SET last_played_at=datetime('now') WHERE article_id=?",
        (article_id,),
    )
    conn.execute(
        "UPDATE reading_state SET status='listened', last_played_at=datetime('now') WHERE article_id=?",
        (article_id,),
    )
    conn.commit()
    return FileResponse(
        row["file_path"],
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline"},
    )


@app.post("/api/refresh")
async def refresh(conn: ConnDep) -> dict:
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(None, refresh_all_feeds, conn)
    return {slug: list(counts) for slug, counts in results.items()}
