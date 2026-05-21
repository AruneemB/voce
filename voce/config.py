"""Environment-based configuration and constants for Voce."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    """Runtime configuration for Voce, populated from environment variables."""

    elevenlabs_api_key: str = field(default_factory=lambda: os.environ.get("ELEVENLABS_API_KEY", ""))
    elevenlabs_voice_id: str = field(default_factory=lambda: os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"))
    elevenlabs_model_id: str = field(default_factory=lambda: os.environ.get("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5"))
    host: str = field(default_factory=lambda: os.environ.get("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("PORT", "8765")))
    db_path: Path = field(default_factory=lambda: Path(os.environ.get("DB_PATH", "data/voce.db")))
    audio_cache_dir: Path = field(default_factory=lambda: Path(os.environ.get("AUDIO_CACHE_DIR", "data/audio_cache")))
    audio_cache_ttl_days: int = field(default_factory=lambda: int(os.environ.get("AUDIO_CACHE_TTL_DAYS", "30")))
    feed_refresh_minutes: int = field(default_factory=lambda: int(os.environ.get("FEED_REFRESH_MINUTES", "30")))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))


def load_settings() -> Settings:
    """Load settings from environment. Raises ValueError if ELEVENLABS_API_KEY is missing."""
    s = Settings()
    if not s.elevenlabs_api_key.strip():
        raise ValueError(
            "ELEVENLABS_API_KEY is not set. "
            "Add it to your .env file or set it as an environment variable."
        )
    return s


settings: Settings = load_settings()
