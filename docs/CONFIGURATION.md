# Ember Memory — Configuration Reference

All settings via environment variables or `~/.ember-memory/config.env`.

## Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBER_BACKEND` | `chromadb` | Storage backend |
| `EMBER_DATA_DIR` | `~/.ember-memory` | Where data is stored |
| `EMBER_EMBEDDING_PROVIDER` | `ollama` | Embedding provider |
| `EMBER_EMBEDDING_MODEL` | `bge-m3` | Ollama embedding model |
| `EMBER_OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model |
| `EMBER_GOOGLE_EMBEDDING_MODEL` | `gemini-embedding-001` | Google embedding model |
| `EMBER_OPENROUTER_EMBEDDING_MODEL` | `baai/bge-m3` | OpenRouter embedding model |
| `EMBER_SIMILARITY_THRESHOLD` | `0.45` | Min similarity for auto-retrieval |
| `EMBER_MAX_HOOK_RESULTS` | `5` | Results injected per message |
| `EMBER_AI_ID_MAP` | empty | Optional custom hook identity mapping, e.g. `writer=codex,reviewer=gemini` |

## Scoring Weights

The Ember Engine scores memory candidates using four signals. Change these to tune how memories are ranked.

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBER_WEIGHT_SIMILARITY` | `0.40` | Semantic match weight |
| `EMBER_WEIGHT_HEAT` | `0.25` | Heat/recency weight |
| `EMBER_WEIGHT_CONNECTION` | `0.20` | Co-occurrence weight |
| `EMBER_WEIGHT_DECAY` | `0.15` | Freshness weight |

## Heat Decay Tuning

If heat feels "sticky" (topics don't cool down fast enough), lower `EMBER_DECAY_INACTIVE` to `0.50` or `0.40`. If heat disappears too quickly, raise `EMBER_DECAY_ACTIVE` to `0.95` or `0.98`.

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBER_DECAY_ACTIVE` | `0.92` | Heat decay for active memories (per tick) |
| `EMBER_DECAY_INACTIVE` | `0.60` | Heat decay for inactive memories (per tick) |
| `EMBER_TIME_DECAY_FACTOR` | `0.95` | Time-based heat decay factor |
| `EMBER_TIME_DECAY_INTERVAL_MINUTES` | `15` | Minutes between time decay ticks |

## Defaults Are Calibrated

Most users never touch these. The defaults come from real usage across our own CLI workflows — they're tuned to feel responsive without being "sticky." Each setting has a description you can search for in the source if you want the full rationale.
