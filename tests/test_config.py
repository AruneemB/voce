import importlib
import os
import pytest


def test_load_settings_raises_when_api_key_missing(monkeypatch):
    """load_settings() must raise ValueError with a clear message when ELEVENLABS_API_KEY is absent."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    import voce.config as cfg
    with pytest.raises(ValueError, match="ELEVENLABS_API_KEY is not set"):
        cfg.load_settings()


def test_load_settings_succeeds_with_api_key(monkeypatch):
    """load_settings() returns a Settings object when ELEVENLABS_API_KEY is present."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-xyz")
    import voce.config as cfg
    importlib.reload(cfg)
    s = cfg.load_settings()
    assert s.elevenlabs_api_key == "test-key-xyz"


def test_default_port_is_8765(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.delenv("PORT", raising=False)
    import voce.config as cfg
    importlib.reload(cfg)
    assert cfg.load_settings().port == 8765
