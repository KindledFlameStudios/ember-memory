"""
Configuration management for Ember Memory.

Resolution order (per setting):
  1. Environment variable   — allows runtime overrides / CI
  2. config.env file        — controller-managed, lives at ~/.ember-memory/config.env
  3. Hardcoded default      — sensible out-of-box values

The config file lives at a FIXED location (~/.ember-memory/config.env) regardless
of where the actual data directory is. This avoids the chicken-and-egg problem:
config.env tells us where the data lives, so it can't live inside the data dir.

The controller app writes config.env. The MCP server and hook both read it here.
"""

import os

# Config home is fixed — always ~/.ember-memory/ regardless of data dir
CONFIG_HOME = os.path.expanduser("~/.ember-memory")
CONFIG_FILE = os.path.join(CONFIG_HOME, "config.env")

# Default data dir (overridable via config.env or env var)
DEFAULT_DATA_DIR = CONFIG_HOME


def _load_config_file():
    """Read EMBER_* key=value pairs from the fixed config.env location."""
    values = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    values[key.strip()] = val.strip()
    return values


# Load file config once at import time
_FILE_CONFIG = _load_config_file()


def _get(key, default):
    """Resolve a config value: env var > config.env > default."""
    env_val = os.environ.get(key)
    if env_val is not None:
        return env_val
    file_val = _FILE_CONFIG.get(key)
    if file_val is not None:
        return file_val
    return default


# ── Storage ──────────────────────────────────────────────────────────────────

BACKEND = _get("EMBER_BACKEND", "chromadb")
DATA_DIR = _get("EMBER_DATA_DIR", DEFAULT_DATA_DIR)

# ── Embedding ────────────────────────────────────────────────────────────────

EMBEDDING_PROVIDER = _get("EMBER_EMBEDDING_PROVIDER", "ollama")
EMBEDDING_MODEL = _get("EMBER_EMBEDDING_MODEL", "bge-m3")
OLLAMA_URL = _get("EMBER_OLLAMA_URL", "http://localhost:11434/api/embeddings")

# ── Search ───────────────────────────────────────────────────────────────────

DEFAULT_COLLECTION = _get("EMBER_DEFAULT_COLLECTION", "general")
SEARCH_LIMIT = int(_get("EMBER_SEARCH_LIMIT", "10"))

# ── Hook ─────────────────────────────────────────────────────────────────────

SIMILARITY_THRESHOLD = float(_get("EMBER_SIMILARITY_THRESHOLD", "0.45"))
MAX_HOOK_RESULTS = int(_get("EMBER_MAX_HOOK_RESULTS", "5"))
MAX_PREVIEW_CHARS = int(_get("EMBER_MAX_PREVIEW_CHARS", "800"))
HOOK_DEBUG = _get("EMBER_HOOK_DEBUG", "").lower() in ("1", "true", "yes")
AUTO_QUERY = _get("EMBER_AUTO_QUERY", "true").lower() in ("1", "true", "yes")

# -- Embedding (cloud providers) --
OPENAI_API_KEY = _get("EMBER_OPENAI_API_KEY", "")
OPENAI_EMBEDDING_MODEL = _get("EMBER_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
GOOGLE_API_KEY = _get("EMBER_GOOGLE_API_KEY", "")
GOOGLE_EMBEDDING_MODEL = _get("EMBER_GOOGLE_EMBEDDING_MODEL", "gemini-embedding-001")
OPENROUTER_API_KEY = _get("EMBER_OPENROUTER_API_KEY", "")
OPENROUTER_EMBEDDING_MODEL = _get("EMBER_OPENROUTER_EMBEDDING_MODEL", "baai/bge-m3")

# -- Engine weights --
WEIGHT_SIMILARITY = float(_get("EMBER_WEIGHT_SIMILARITY", "0.40"))
WEIGHT_HEAT = float(_get("EMBER_WEIGHT_HEAT", "0.25"))
WEIGHT_CONNECTION = float(_get("EMBER_WEIGHT_CONNECTION", "0.20"))
WEIGHT_DECAY = float(_get("EMBER_WEIGHT_DECAY", "0.15"))

# -- Namespace mode --
# "scoped" = each CLI sees shared + its own private collections (default)
# "open" = all CLIs see all collections (single AI setup)
NAMESPACE_MODE = _get("EMBER_NAMESPACE_MODE", "scoped")

# -- Context tag --
CONTEXT_TAG = _get("EMBER_CONTEXT_TAG", "ember-memory")
