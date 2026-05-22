# Deployment

Voce is designed to run locally on your machine as a persistent background process. This document covers starting the server, all CLI flags, every environment variable, and how to run Voce as a system service.

---

## Starting the server

```bash
python -m voce
```

Or, if you installed Voce with `pip install -e .`:

```bash
voce
```

On first start, Voce:

1. Validates that `ELEVENLABS_API_KEY` is set (exits immediately if missing)
2. Creates `data/voce.db` and bootstraps the schema
3. Creates `data/audio_cache/` for MP3 storage
4. Starts the background scheduler (feed refresh + cache sweep)
5. Begins an initial feed refresh
6. Opens `http://127.0.0.1:8765` in your default browser

---

## CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Interface to bind. Do not change this to `0.0.0.0` — Voce is localhost-only by design. |
| `--port` | `8765` | Port to listen on |
| `--log-level` | `info` | Uvicorn log level: `debug`, `info`, `warning`, `error`, `critical` |
| `--refresh-now` | — | Immediately refresh all feeds and exit (no HTTP server started) |
| `--sweep-cache` | — | Prune expired audio cache entries and exit (no HTTP server started) |
| `--no-browser` | — | Do not auto-open the browser on startup |
| `--verbose` | — | Enable per-request HTTP access logging |

Examples:

```bash
# Run on a different port
python -m voce --port 9000

# Refresh feeds without starting the server (useful in cron)
python -m voce --refresh-now

# Prune stale audio files
python -m voce --sweep-cache

# Start without opening a browser tab
python -m voce --no-browser
```

---

## Environment variables

All settings can be configured via environment variables (in `.env` or in the shell environment). The table below lists every variable, its default value, and whether it is required.

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `ELEVENLABS_API_KEY` | — | **Yes** | Your ElevenLabs API key. The server will not start without it. |
| `ELEVENLABS_VOICE_ID` | `21m00Tcm4TlvDq8ikWAM` | No | ElevenLabs voice ID to use for synthesis. The default is the "Rachel" voice. |
| `ELEVENLABS_MODEL_ID` | `eleven_turbo_v2_5` | No | ElevenLabs model ID. `eleven_turbo_v2_5` balances quality and cost. |
| `HOST` | `127.0.0.1` | No | Interface to bind (overridden by `--host`). |
| `PORT` | `8765` | No | Port to listen on (overridden by `--port`). |
| `DB_PATH` | `data/voce.db` | No | Path to the SQLite database file. Created automatically if it does not exist. |
| `AUDIO_CACHE_DIR` | `data/audio_cache` | No | Directory for cached MP3 files. Created automatically if it does not exist. |
| `AUDIO_CACHE_TTL_DAYS` | `30` | No | Audio files not played within this many days are deleted by the cache sweep. |
| `FEED_REFRESH_MINUTES` | `30` | No | Interval between automatic feed refreshes. |
| `LOG_LEVEL` | `INFO` | No | Application log level for loguru output. |

Copy `.env.example` to `.env` and edit it. The file is loaded automatically on startup via `python-dotenv`.

---

## Scheduler behaviour

Voce runs two background jobs:

**Feed refresh**
- Runs immediately on startup, then every `FEED_REFRESH_MINUTES` minutes
- Fetches all four Quanta Magazine sections
- New articles are inserted; existing articles are skipped
- Per-section counts are logged at `INFO` level

**Cache sweep**
- Runs on startup and then daily at 03:00 local time
- Deletes `audio_cache` rows where `last_played_at` is older than `AUDIO_CACHE_TTL_DAYS`
- Deletes the corresponding MP3 files from disk
- Sweep results are logged at `INFO` level

---

## Cache management

The audio cache lives in `data/audio_cache/`. Each synthesised article produces one MP3 file named `{article_id}.mp3`.

**Automatic sweep:** The scheduler prunes files daily based on `AUDIO_CACHE_TTL_DAYS`. Files that have not been played within the TTL window are deleted.

**Manual sweep:** Run `python -m voce --sweep-cache` to trigger an immediate sweep and exit.

**Manual deletion:** You can delete individual MP3 files directly from `data/audio_cache/`. Voce will re-synthesise them on demand. If the database row in `audio_cache` still exists but the file is gone, the next stream request will fail with a 404 — simply re-trigger synthesis from the UI.

---

## Log files

By default, Voce logs to stdout only, using loguru. Log lines follow the format:

```
HH:mm:ss LEVEL   module: message
```

**File logging** (Phase 10): Passing `--verbose` enables a rotating file handler at `data/voce.log`.

**Log levels:**
- `INFO` — feed refresh counts, cache sweep results, synthesis completions
- `WARNING` — retry attempts, cost guard refusals, articles that could not be enriched
- `ERROR` — persistent feed failures after all retries exhausted

---

## Running as a system service

### macOS (launchd)

Create `~/Library/LaunchAgents/com.voce.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.voce</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/.venv/bin/python</string>
    <string>-m</string>
    <string>voce</string>
    <string>--no-browser</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/path/to/voce</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>ELEVENLABS_API_KEY</key>
    <string>your_key_here</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/voce.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/voce.err</string>
</dict>
</plist>
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.voce.plist
```

### Linux (systemd)

Create `/etc/systemd/system/voce.service`:

```ini
[Unit]
Description=Voce TTS companion
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/voce
Environment=ELEVENLABS_API_KEY=your_key_here
ExecStart=/path/to/.venv/bin/python -m voce --no-browser
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable voce
sudo systemctl start voce
```
