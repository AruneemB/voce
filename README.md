# Voce

*A personal listening companion for Quanta Magazine.*

Voce turns Quanta Magazine's science journalism into narrated audio, served privately on your own machine. It ingests RSS feeds, converts article HTML into clean prose, synthesises narration via ElevenLabs, and streams the result through a browser interface — all without leaving localhost.

---

## Why Voce exists

Quanta Magazine publishes some of the finest science writing available, and reading it well requires attention. Voce is for the times when you want to listen instead — on a walk, at a desk, in the gap between tasks. It treats the act of listening as something worth designing for: clean narration, sensible pacing, and attribution on every article.

The design is deliberate about what it is not. Voce is not a podcast platform, a content distributor, or a cloud service. It binds only to localhost, sources content only from Quanta's own RSS feeds, keeps no permanent audio archive, and attributes every narration to its original author and publication. The audio cache expires automatically. These are not limitations — they are how Voce stays honest about what it is for.

---

## Principles

- **RSS-only sourcing** — content comes from Quanta Magazine's public feeds, not page scraping
- **Localhost binding** — the server is inaccessible outside your machine; this is enforced in middleware, not just by convention
- **Attribution on every narration** — each synthesised audio begins with title, author, and publication date
- **Auto-expiring cache** — synthesised audio expires after a configurable number of days; nothing accumulates indefinitely
- **No redistribution surface** — audio is served inline to your browser only, never as a downloadable export

---

## Quick start

```bash
git clone https://github.com/AruneemB/voce.git
cd voce
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env          # then set ELEVENLABS_API_KEY in .env
python -m voce
```

Voce opens at `http://127.0.0.1:8765`. Articles appear as the first feed refresh completes.

---

## Documentation

| Guide | Contents |
|-------|----------|
| [Getting Started](docs/GETTING-STARTED.md) | Prerequisites, installation, first-run walkthrough, common issues |
| [API Reference](docs/API-REFERENCE.md) | All endpoints — request parameters, response schemas, error codes |
| [Architecture](docs/ARCHITECTURE.md) | System design, data flow, layer breakdown, design decisions |
| [Components](docs/COMPONENTS.md) | Every module — what it owns, key functions, invariants |
| [Database](docs/DATABASE.md) | Full schema — tables, indexes, triggers, FTS5, data lifecycle |
| [Deployment](docs/DEPLOYMENT.md) | CLI flags, environment variables, running as a system service |
| [Development](docs/DEVELOPMENT.md) | Dev setup, test suite, coding conventions, how to extend |
| [Roadmap](docs/ROADMAP.md) | What is complete, what is coming, what is out of scope |

---

## Requirements

- Python 3.11+
- An [ElevenLabs](https://elevenlabs.io) account and API key

---

*Content is sourced from [Quanta Magazine](https://www.quantamagazine.org) via their public RSS feeds and remains their copyright. Voce is a personal listening tool, not a redistribution service.*
