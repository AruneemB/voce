# API Reference

Voce exposes a JSON API served by FastAPI on `http://127.0.0.1:8765` by default. All endpoints are read-only except where noted.

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

### `GET /api/articles/{article_id}/topics`

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

### `GET /api/search`

Full-text search across article titles and body text.

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

Returns all articles currently marked as `queued`, ordered by when they were queued (most recent first).

**Response** — `200 OK` — same shape as `GET /api/articles` (without pagination; returns all queued articles)

---

## Reading state

### `POST /api/articles/{article_id}/state`

Updates the reading status of an article.

**Request body**

```json
{ "status": "queued" }
```

| Field | Allowed values |
|-------|---------------|
| `status` | `"unread"`, `"queued"`, `"listened"` |

**Response** — `200 OK`

```json
{ "article_id": "a3f2b1c8d4e5f6a7", "status": "queued" }
```

**Error responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | No article with the given ID exists |
| `422 Unprocessable Entity` | Invalid status value |

---

## Audio

### `POST /api/articles/{article_id}/audio`

Triggers TTS synthesis for an article. If synthesis is already cached, returns immediately. If synthesis is in progress or not yet started, returns a `202 Accepted` response.

**Response** — `200 OK` (audio ready)

```json
{
  "article_id": "a3f2b1c8d4e5f6a7",
  "status": "ready",
  "duration_sec": 312
}
```

**Response** — `202 Accepted` (synthesis queued or in progress)

```json
{
  "article_id": "a3f2b1c8d4e5f6a7",
  "status": "pending"
}
```

**Error responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | No article with the given ID exists |
| `413 Content Too Large` | Article body exceeds 50,000 characters; synthesis refused to prevent excessive API cost |
| `500 Internal Server Error` | ElevenLabs synthesis failed |

---

### `GET /api/articles/{article_id}/audio/status`

Polls the synthesis status for an article without triggering synthesis.

**Response** — `200 OK`

```json
{
  "article_id": "a3f2b1c8d4e5f6a7",
  "status": "ready",
  "duration_sec": 312
}
```

| `status` value | Meaning |
|----------------|---------|
| `"ready"` | Audio is cached and available for streaming |
| `"pending"` | Synthesis has not yet been triggered |
| `"synthesising"` | Synthesis is currently in progress |

---

### `GET /api/articles/{article_id}/audio/stream`

Streams the cached MP3 file for an article. Supports HTTP range requests for seek support in the browser audio player.

**Headers**

| Header | Value |
|--------|-------|
| `Content-Type` | `audio/mpeg` |
| `Content-Disposition` | `inline` |
| `Accept-Ranges` | `bytes` |

**Error responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | No audio cached for this article (trigger synthesis first) |

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

Returns `voce/static/index.html` — the single-page browser UI. All subsequent UI data fetches go through the JSON endpoints above.
