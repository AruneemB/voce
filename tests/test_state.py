import sqlite3

import pytest
from fastapi.testclient import TestClient

from voce.api import app, get_conn
from voce.db import bootstrap_schema


@pytest.fixture
def client():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_schema(conn)
    conn.execute(
        "INSERT INTO articles (id, section, title, published_at, url, body_html, body_text) "
        "VALUES ('art1','physics','T','2024-01-01T00:00:00Z','https://x.com','','.')"
    )
    conn.execute("INSERT INTO reading_state (article_id, status) VALUES ('art1', 'unread')")
    conn.commit()
    app.dependency_overrides[get_conn] = lambda: conn
    with TestClient(app, headers={"host": "127.0.0.1:8765"}) as c:
        yield c
    app.dependency_overrides.clear()
    conn.close()


def test_state_transition_to_queued(client):
    resp = client.post("/api/articles/art1/state", json={"status": "queued"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


def test_state_transition_to_listened(client):
    resp = client.post("/api/articles/art1/state", json={"status": "listened"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "listened"


def test_state_transition_to_unread_clears_last_played(client):
    listened_resp = client.post("/api/articles/art1/state", json={"status": "listened"})
    assert listened_resp.json()["last_played_at"] is not None, "listened should set last_played_at"
    resp = client.post("/api/articles/art1/state", json={"status": "unread"})
    assert resp.status_code == 200
    assert resp.json()["last_played_at"] is None


def test_state_invalid_value_returns_422(client):
    resp = client.post("/api/articles/art1/state", json={"status": "invalid"})
    assert resp.status_code == 422


def test_state_404_for_missing_article(client):
    resp = client.post("/api/articles/nonexistent/state", json={"status": "queued"})
    assert resp.status_code == 404


def test_queue_returns_only_queued(client):
    client.post("/api/articles/art1/state", json={"status": "queued"})
    resp = client.get("/api/queue")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["status"] == "queued"


def test_scheduler_has_two_jobs():
    from voce.scheduler import build_scheduler
    s = build_scheduler(lambda: None)
    assert len(s.get_jobs()) == 2
    job_ids = {j.id for j in s.get_jobs()}
    assert "feed_refresh" in job_ids
    assert "cache_sweep" in job_ids


# ── Edge case and scheduler configuration tests ───────────────────────────────


@pytest.fixture
def client_two_articles():
    """Fixture with two articles seeded for ordering and exclusion tests."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_schema(conn)
    for art_id, url in [("art1", "https://x.com/1"), ("art2", "https://x.com/2")]:
        conn.execute(
            "INSERT INTO articles (id, section, title, published_at, url, body_html, body_text) "
            "VALUES (?, 'physics', 'T', '2024-01-01T00:00:00Z', ?, '', '.')",
            (art_id, url),
        )
        conn.execute(
            "INSERT INTO reading_state (article_id, status) VALUES (?, 'unread')", (art_id,)
        )
    conn.commit()
    app.dependency_overrides[get_conn] = lambda: conn
    with TestClient(app, headers={"host": "127.0.0.1:8765"}) as c:
        yield c, conn
    app.dependency_overrides.clear()
    conn.close()


@pytest.fixture
def client_no_reading_state():
    """Article exists but has no reading_state row — exercises the UPSERT INSERT branch."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_schema(conn)
    conn.execute(
        "INSERT INTO articles (id, section, title, published_at, url, body_html, body_text) "
        "VALUES ('art2','physics','T2','2024-01-01T00:00:00Z','https://y.com','','.')"
    )
    conn.commit()
    app.dependency_overrides[get_conn] = lambda: conn
    with TestClient(app, headers={"host": "127.0.0.1:8765"}) as c:
        yield c
    app.dependency_overrides.clear()
    conn.close()


def test_state_upsert_creates_row_when_none_exists(client_no_reading_state):
    resp = client_no_reading_state.post("/api/articles/art2/state", json={"status": "queued"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


def test_queue_empty_when_no_articles_queued(client):
    resp = client.get("/api/queue")
    assert resp.status_code == 200
    assert resp.json() == []


def test_queue_excludes_unread_and_listened(client_two_articles):
    c, _conn = client_two_articles
    c.post("/api/articles/art1/state", json={"status": "listened"})
    resp = c.get("/api/queue")
    assert resp.status_code == 200
    assert resp.json() == []


def test_queue_ordering_by_updated_at(client_two_articles):
    c, conn = client_two_articles
    # Set different updated_at values directly so the order is deterministic
    conn.execute(
        "INSERT INTO reading_state (article_id, status, updated_at) VALUES ('art2','queued','2024-01-01T10:00:00Z') "
        "ON CONFLICT(article_id) DO UPDATE SET status='queued', updated_at='2024-01-01T10:00:00Z'"
    )
    conn.execute(
        "INSERT INTO reading_state (article_id, status, updated_at) VALUES ('art1','queued','2024-01-01T11:00:00Z') "
        "ON CONFLICT(article_id) DO UPDATE SET status='queued', updated_at='2024-01-01T11:00:00Z'"
    )
    conn.commit()
    resp = c.get("/api/queue")
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()]
    assert ids[0] == "art2"
    assert ids[1] == "art1"


def test_refresh_job_calls_enrichment_after_feed_refresh():
    """_refresh_job must invoke enrich_all_unenriched after refresh_all_feeds.

    Asserts call order and that both functions receive the same (conn, client)
    pair, pinning the enrichment wiring against future scheduler refactors.
    """
    from unittest.mock import MagicMock, patch
    from voce.scheduler import _refresh_job

    mock_conn = MagicMock()
    conn_factory = MagicMock(return_value=mock_conn)

    seq: list = []

    with patch("voce.scheduler.refresh_all_feeds") as mock_refresh, \
         patch("voce.scheduler.enrich_all_unenriched") as mock_enrich, \
         patch("voce.scheduler.httpx.Client") as mock_client_cls:
        mock_refresh.return_value = {}
        mock_enrich.return_value = (0, 0)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = ctx

        def _record_refresh(*a, **k):
            seq.append(("refresh", a, k))
            return {}

        def _record_enrich(*a, **k):
            seq.append(("enrich", a, k))
            return (0, 0)

        mock_refresh.side_effect = _record_refresh
        mock_enrich.side_effect = _record_enrich

        _refresh_job(conn_factory)

    assert len(seq) == 2
    assert seq[0][0] == "refresh"
    assert seq[1][0] == "enrich"
    # refresh_all_feeds receives only conn; enrich_all_unenriched receives conn + client
    assert seq[0][1] == (mock_conn,), "refresh must receive (conn,)"
    assert seq[1][1] == (mock_conn, ctx), "enrich must receive (conn, client)"


def test_refresh_job_enrichment_uses_certifi():
    """_refresh_job must pass certifi.where() to its httpx.Client."""
    import certifi
    from unittest.mock import MagicMock, patch
    from voce.scheduler import _refresh_job

    conn_factory = MagicMock(return_value=MagicMock())

    with patch("voce.scheduler.refresh_all_feeds", return_value={}), \
         patch("voce.scheduler.enrich_all_unenriched", return_value=(0, 0)), \
         patch("voce.scheduler.httpx.Client") as mock_client_cls:
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = ctx

        _refresh_job(conn_factory)

    kwargs = mock_client_cls.call_args.kwargs
    assert kwargs.get("verify") == certifi.where()
    assert kwargs.get("follow_redirects") is True


def test_scheduler_feed_refresh_job_config():
    from voce.config import settings
    from voce.scheduler import build_scheduler
    s = build_scheduler(lambda: None)
    job = next(j for j in s.get_jobs() if j.id == "feed_refresh")
    # total_seconds() is correct for intervals >= 24 h; .seconds would be modulo 86 400
    assert job.trigger.interval.total_seconds() // 60 == settings.feed_refresh_minutes


def test_scheduler_cache_sweep_job_config():
    from apscheduler.triggers.cron import CronTrigger
    from voce.scheduler import build_scheduler
    s = build_scheduler(lambda: None)
    job = next(j for j in s.get_jobs() if j.id == "cache_sweep")
    # Locate hour field by canonical index rather than assuming field.name presence
    hour_index = CronTrigger.FIELD_NAMES.index("hour")
    hour_field = job.trigger.fields[hour_index]
    assert str(hour_field) == "3"
