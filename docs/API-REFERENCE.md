# API Reference

Voce exposes a JSON API served by FastAPI on `http://127.0.0.1:8765` by default. All endpoints are read-only except where noted.

## Implementation status

Not all endpoints described in this reference are implemented yet. The table below reflects the current state of the codebase.

| Endpoint | Status | Phase |
|----------|--------|-------|
| `GET /` | Implemented | 5 |
| `GET /api/sections` | Implemented | 5 |
| `GET /api/articles` | Implemented | 5 |
| `GET /api/articles/{id}` | Implemented | 5 |
| `GET /api/topics` | Implemented | 5 |
| `POST /api/refresh` | Implemented | 5 |
| `GET /api/articles/{id}/topics` | Planned | 9 |
| `GET /api/search` | Planned | 10 |
| `GET /api/queue` | Implemented | 9 |
| `POST /api/articles/{id}/state` | Implemented | 9 |
| `POST /api/articles/{id}/audio` | Implemented | 8 |
| `GET /api/articles/{id}/audio/status` | Implemented | 8 |
| `GET /api/articles/{id}/audio/stream` | Implemented | 8 |

> **Note on search:** The frontend (`app.js`) attempts `GET /api/search?q=` first and falls back to `GET /api/articles?q=` on a `404`. This means full-text search works today via the `q` parameter on `/api/articles`. The dedicated `/api/search` endpoint (with richer response metadata) is a Phase 10 addition.

---

## Access policy

Every request passes through `LocalhostOnlyMiddleware`, which enforces two independent checks:

1. **Client IP** — the connecting socket must originate from a loopback address (`127.0.0.1` or `::1`). This check cannot be spoofed via headers.
2. **Host header** — the `Host` header must be exactly `127.0.0.1:<port>` or `localhost:<port>`. This defends against DNS-rebinding attacks.

Any request that fails either check receives **403 Forbidden** with the body `Forbidden: remote access not allowed`.

---

## Conventions

- Base URL: `http://127.0.0.1:8765` (or the port you configured)
- All responses are bare JSON — no envelope wrapper
- Timestamps are ISO 8601 strings in UTC (e.g. `"2024-03-15T14:30:00Z"`)
- Pagination uses `limit` + `offset` query parameters
- `null` fields are included in responses (not omitted)

---

## Sections

### `GET /api/sections`

Returns all four Quanta Magazine sections with their unread article counts.

**Response** — `200 OK`, array of section objects

```json
[
  {
    "section": "physics",
    "display_name": "Physics",
    "unread_count": 12
  },
  {
    "section": "mathematics",
    "display_name": "Mathematics",
    "unread_count": 8
  },
  {
    "section": "biology",
    "display_name": "Biology",
    "unread_count": 5
  },
  {
    "section": "computer-science",
    "display_name": "Computer Science",
    "unread_count": 19
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `section` | string | Machine-readable slug |
| `display_name` | string | Human-readable label |
| `unread_count` | integer | Articles with status `"unread"` in this section |

---

## Articles

### `GET /api/articles`

Returns a paginated list of article summaries, with optional filters.

**Query parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `section` | string | — | Filter to a single section slug |
| `status` | string | — | Filter by reading status: `unread`, `queued`, or `listened` |
| `topic` | string | — | Filter to articles tagged with this topic slug |
| `q` | string | — | Full-text search query (FTS5, falls back to LIKE) |
| `limit` | integer | `30` | Results per page (1–100) |
| `offset` | integer | `0` | Number of results to skip |

**Response** — `200 OK`

```json
{
  "items": [
    {
      "id": "a3f2b1c8d4e5f6a7",
      "section": "physics",
      "title": "How Quantum Mechanics Defies Intuition",
      "author": "Natalie Wolchover",
      "published_at": "2024-03-15T00:00:00Z",
      "url": "https://www.quantamagazine.org/...",
      "summary": "A brief overview of the article...",
      "status": "unread",
      "quanta_audio_url": null
    }
  ],
  "total": 47,
  "limit": 30,
  "offset": 0
}
```

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `items` | array | — | Article summary objects |
| `total` | integer | — | Total matching articles (ignoring pagination) |
| `limit` | integer | — | Limit applied to this response |
| `offset` | integer | — | Offset applied to this response |

**Article summary fields**

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `id` | string | No | SHA-256 derived article identifier (16 hex chars) |
| `section` | string | No | Section slug |
| `title` | string | No | Article title |
| `author` | string | Yes | Author name; `null` if not present in feed |
| `published_at` | string | No | ISO 8601 UTC publication timestamp |
| `url` | string | No | Canonical URL on quantamagazine.org |
| `summary` | string | Yes | RSS feed summary excerpt |
| `status` | string | No | Reading status: `unread`, `queued`, or `listened` |
| `quanta_audio_url` | string | Yes | Quanta's own narration URL if provided in the RSS feed |

---

### `GET /api/articles/{article_id}`

Returns the full detail for a single article, including cleaned body text.

**Path parameters**

| Parameter | Description |
|-----------|-------------|
| `article_id` | The 16-character hex article ID |

**Response** — `200 OK`

All fields from the article summary, plus:

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `body_text` | string | No | Prose-ready plain text after HTML cleanup and LaTeX conversion. Includes an attribution preamble. |

**Error responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | No article with the given ID exists in the database |

---

### `GET /api/articles/{article_id}/topics` _(planned — Phase 9)_

Returns the topic tags associated with a single article.

**Response** — `200 OK`, array of strings

```json
["quantum-mechanics", "particle-physics", "black-holes"]
```

---

## Topics

### `GET /api/topics`

Returns all topics across the article catalogue, with article counts.

**Query parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `section` | string | — | Limit to topics that appear in this section |

**Response** — `200 OK`, array of topic objects

```json
[
  {
    "slug": "black-holes",
    "label": "Black Holes",
    "article_count": 7
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `slug` | string | Machine-readable topic identifier |
| `label` | string | Title-cased display label derived from the slug |
| `article_count` | integer | Number of articles tagged with this topic |

---

## Search

### `GET /api/search` _(planned — Phase 10)_

Full-text search across article titles and body text.

> **Current behaviour:** Full-text search is available today via the `q` parameter on `GET /api/articles` (e.g. `/api/articles?q=black+holes`). The frontend falls back to this endpoint when `/api/search` returns 404. The dedicated `/api/search` endpoint will expose richer response metadata and may support additional filtering options.

**Query parameters**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `q` | string | Yes | Search query |
| `limit` | integer | No | Results per page (1–100, default 30) |
| `offset` | integer | No | Offset for pagination (default 0) |

Voce uses SQLite's FTS5 engine for efficient full-text search. If the FTS query syntax is invalid, the API falls back to a `LIKE`-based substring search.

**Response** — `200 OK` — same shape as `GET /api/articles`

---

## Queue

### `GET /api/queue`

Returns all articles currently marked as `queued`, ordered by when they were queued (oldest first — `updated_at ASC`). Returns all queued articles in a single response (no pagination).

**Response** — `200 OK`, array of article summary objects

Same field shape as the items array in `GET /api/articles` (see article summary fields above). All returned items have `"status": "queued"`.

```json
[
  {
    "id": "a3f2b1c8d4e5f6a7",
    "section": "physics",
    "title": "How Quantum Mechanics Defies Intuition",
    "author": "Natalie Wolchover",
    "published_at": "2024-03-15T00:00:00Z",
    "url": "https://www.quantamagazine.org/...",
    "summary": "A brief overview of the article...",
    "status": "queued",
    "quanta_audio_url": null
  }
]
```

Returns an empty array when no articles are queued.

---

## Reading state

### `POST /api/articles/{article_id}/state`

Updates the reading status of an article. Uses an UPSERT — creating the `reading_state` row if it does not yet exist, or updating the existing one. All three state transitions are valid in any order.

**Path parameters**

| Parameter | Description |
|-----------|-------------|
| `article_id` | The 16-character hex article ID |

**Request body**

```json
{ "status": "queued" }
```

| Field | Allowed values |
|-------|---------------|
| `status` | `"unread"`, `"queued"`, `"listened"` |

**State transition rules**

| New status | `last_played_at` | `updated_at` |
|------------|------------------|--------------|
| `"queued"` | unchanged | set to `now` |
| `"listened"` | set to `now` | set to `now` |
| `"unread"` | set to `NULL` | set to `now` |

**Response** — `200 OK`

```json
{
  "article_id": "a3f2b1c8d4e5f6a7",
  "status": "queued",
  "last_played_at": null,
  "updated_at": "2024-03-15T14:30:00Z"
}
```

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `article_id` | string | No | The article ID that was updated |
| `status` | string | No | New status: `unread`, `queued`, or `listened` |
| `last_played_at` | string | Yes | UTC timestamp of last audio stream, or `null` |
| `updated_at` | string | No | UTC timestamp of this status change |

**Error responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | No article with the given ID exists |
| `422 Unprocessable Entity` | `status` is not one of `unread`, `queued`, `listened` |

---

## Audio

### `POST /api/articles/{article_id}/audio`

Triggers on-demand TTS synthesis for an article. Returns immediately in all cases — synthesis runs in a background thread. Checking progress requires polling `GET /api/articles/{article_id}/audio/status`.

**Response** — `202 Accepted` (synthesis started or already in progress)

```json
{ "status": "pending" }
```

**Response** — `202 Accepted` (audio is already cached — no synthesis needed)

```json
{
  "status": "ready",
  "url": "/api/articles/a3f2b1c8d4e5f6a7/audio/stream"
}
```

**Error responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | No article with the given ID exists in the database |

> **Cost guard:** `synthesize_article()` refuses articles whose narration text exceeds 50,000 characters and logs a `WARNING`. The background task catches this and logs it; the endpoint itself has already returned `202`.

---

### `GET /api/articles/{article_id}/audio/status`

Returns the current audio state for an article without triggering synthesis. The frontend polls this endpoint (every 2 seconds, up to 60 attempts) after `POST /api/articles/{article_id}/audio` returns `"pending"`.

**Response** — `200 OK`

```json
{
  "cached": true,
  "url": "/api/articles/a3f2b1c8d4e5f6a7/audio/stream",
  "duration_sec": 312,
  "pending": false
}
```

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `cached` | boolean | No | `true` if an `audio_cache` row exists *and* the MP3 file is present on disk |
| `url` | string | Yes | Stream URL (`/api/articles/{id}/audio/stream`) when `cached` is true; `null` otherwise |
| `duration_sec` | integer | Yes | Audio duration in seconds when `cached` is true; `null` otherwise |
| `pending` | boolean | No | `true` if synthesis is currently running in a background thread |

When `cached` is `false` and `pending` is `false`, no synthesis has been started — click "Listen with Voce" to begin.

> **Stale-row recovery:** If an `audio_cache` row exists but the MP3 file has been deleted from disk, the endpoint removes the stale row and returns `cached: false`. The same recovery runs in `POST /api/articles/{article_id}/audio` and `GET /api/articles/{article_id}/audio/stream`.

---

### `GET /api/articles/{article_id}/audio/stream`

Serves the cached MP3 file via `FileResponse`. Also updates `audio_cache.last_played_at` (used by the cache sweep for expiry) and sets `reading_state.status` to `"listened"`.

**Response** — `200 OK`

| Header | Value |
|--------|-------|
| `Content-Type` | `audio/mpeg` |
| `Content-Disposition` | `inline` |

**Error responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | No audio cached for this article — trigger synthesis first via `POST /api/articles/{article_id}/audio` |

---

## Admin

### `POST /api/refresh`

Triggers an immediate feed refresh for all four Quanta Magazine sections. This is the same operation the background scheduler runs on its configured interval.

**Response** — `200 OK`

```json
{
  "physics": [3, 14],
  "mathematics": [1, 22],
  "biology": [0, 18],
  "computer-science": [5, 11]
}
```

Each value is a two-element array: `[inserted, skipped]`. Articles already in the database are skipped (not re-inserted); new articles are inserted.

---

## Frontend

### `GET /`

Returns `voce/static/index.html` — the single-page browser UI. The HTML shell, JavaScript, and CSS are also accessible at their static paths:

| Path | Description |
|------|-------------|
| `GET /` | Application shell (`index.html`) |
| `GET /static/app.js` | All application JavaScript |
| `GET /static/styles.css` | Custom CSS (prose, cards, badges, toast) |
| `GET /static/favicon.svg` | Browser tab icon |

All subsequent UI data fetches go through the JSON endpoints documented above. The browsing UI (Phase 6), audio playback (Phase 8), and reading status mutation (Phase 9) are fully implemented. State toggle buttons (Queue / Mark Listened / Mark Unread) appear in the article detail view and post to `POST /api/articles/{id}/state`.
