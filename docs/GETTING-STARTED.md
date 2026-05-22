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

```
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

**Sections sidebar** — The left sidebar lists the four Quanta Magazine sections (Physics, Mathematics, Biology, Computer Science). Each shows a count of unread articles. Counts may read zero until the first feed refresh completes.

**Article list** — Clicking a section populates the main panel with article cards. Each card shows the title, author, publication date, and reading status.

**Article detail** — Clicking an article card opens the full article view with the cleaned body text. A synthesise button triggers audio generation via ElevenLabs. The first synthesis for any article takes several seconds; subsequent plays stream from the local cache instantly.

**Reading status** — Each article can be marked as unread, queued, or listened. Status persists across server restarts.

---

## Verifying your setup

A working setup satisfies all of the following:

- The browser opens automatically and shows the Voce header
- The Physics, Mathematics, Biology, and Computer Science sections appear in the sidebar
- Article cards appear after a few seconds (the feed refresh completes in the background)
- Clicking an article card shows the article detail pane with body text
- Clicking synthesise generates audio and the player appears

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
Voce calls `webbrowser.open()` on startup. If your environment does not support this, navigate manually to `http://127.0.0.1:8765`. Use `--no-browser` to suppress the auto-open permanently.
