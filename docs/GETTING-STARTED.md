# Getting Started with Voce

This guide walks you from a fresh clone to your first article narration. The whole process takes about five minutes.

---

## Prerequisites

| Requirement | Minimum version | Notes |
|-------------|----------------|-------|
| Python | 3.11 | Earlier versions are not supported |
| pip | bundled with Python | Used to install dependencies |
| ElevenLabs account | — | A free-tier account is sufficient for personal use |

You will need an **ElevenLabs API key**. Retrieve it from your ElevenLabs dashboard under **Profile → API keys**.

---

## 1. Clone the repository

```bash
git clone https://github.com/AruneemB/voce.git
cd voce
```

---

## 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

---

## 3. Install dependencies

```bash
pip install -e .
```

This installs Voce and all its dependencies in editable mode. The `-e` flag means changes you make to the source are reflected immediately without reinstalling.

---

## 4. Configure your environment

Copy the example environment file and fill in your API key:

```bash
cp .env.example .env
```

Open `.env` and set your key:

```env
ELEVENLABS_API_KEY=your_key_here
```

All other settings have sensible defaults. See [DEPLOYMENT.md](DEPLOYMENT.md) for the full list of environment variables.

---

## 5. Start the server

```bash
python -m voce
```

Voce will:

1. Bootstrap the SQLite database (creates `data/voce.db` on first run)
2. Begin fetching articles from Quanta Magazine's RSS feeds
3. Open your default browser to `http://127.0.0.1:8765`

You should see the Voce interface load within a few seconds. The initial feed refresh runs in the background; articles appear as they are ingested.

---

## First-run experience

**Sections sidebar** — The left sidebar lists the four Quanta Magazine sections (Physics, Mathematics, Biology, Computer Science). Each section button shows a count of unread articles. Counts may read zero until the first feed refresh completes. Clicking a section filters the article list to that section; clicking again while it is active deselects it and returns to all articles.

**Status filters** — Below the section list, four buttons (All, Unread, Queued, Listened) filter the article list by reading status. "All" is selected by default.

**Article list** — Article cards populate the centre panel. Each card shows the title, author, publication date, a 200-character summary excerpt, and a colour-coded reading status badge (blue for unread, yellow for queued, green for listened). Scroll to the bottom of the list to automatically load the next page.

**Search** — Typing in the search box in the header filters articles using full-text search. The search is debounced by 300 ms and updates the article list as you type. Clearing the search box restores the full article list.

**Article detail** — Clicking an article card opens the full article in the right panel. The URL in your browser's address bar updates to `#article/{id}`, so you can bookmark or navigate directly to any article. An "Open in Quanta ↗" link at the top opens the original article on Quanta Magazine in a new tab. The body text is rendered as clean prose.

**Refresh** — The Refresh button in the header triggers an immediate feed refresh. A green toast notification confirms the refresh started. New articles appear after a short delay.

---

## Verifying your setup

A working setup satisfies all of the following:

- The browser opens automatically and shows the Voce header with the wordmark and tagline
- The Physics, Mathematics, Biology, and Computer Science sections appear in the sidebar with unread counts
- Article cards appear after a few seconds (the initial feed refresh completes in the background)
- Clicking a section button filters the article list to that section
- Clicking an article card shows the article detail pane with prose body text and an "Open in Quanta ↗" link
- The URL updates to `#article/{id}` when an article is selected, and navigating to that URL directly opens the article
- Scrolling to the bottom of the article list loads the next page automatically
- Typing in the search box filters articles in real time

---

## Common first-run issues

**`ELEVENLABS_API_KEY is not set`**
The server exits immediately if the key is missing. Open `.env` and confirm the key is present and correctly formatted (no extra spaces or quotes).

**`Address already in use`**
Port 8765 is occupied by another process. Either stop that process or start Voce on a different port:

```bash
python -m voce --port 9000
```

**No articles appear**
The feed refresh is still in progress. Wait 15–30 seconds and refresh the page. If articles still do not appear, check the terminal for any `ERROR` log lines from the feed ingestion step.

**Browser does not open automatically**
Navigate manually to `http://127.0.0.1:8765`. Use `--no-browser` to suppress the auto-open on future starts.
