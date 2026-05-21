import os

# Provide a dummy API key so env-validated imports (voce.config, voce.db) succeed
# during test collection without requiring a real key in the environment.
os.environ.setdefault("ELEVENLABS_API_KEY", "test-key-for-pytest")
