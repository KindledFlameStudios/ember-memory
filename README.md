# Ember Memory

**Persistent semantic memory for Claude Code.**

Give your AI partner memory that lasts between sessions. Ember Memory stores knowledge in a local vector database and automatically retrieves relevant context on every message — no manual recall needed.

Built with [ChromaDB](https://www.trychroma.com/) and [Ollama](https://ollama.com) embeddings. Everything runs locally. Your memories never leave your machine.

---

## What It Does

- **Stores knowledge** — Architecture decisions, debugging insights, project context, anything worth remembering
- **Auto-retrieves** — A hook fires on every message, searching all collections and injecting relevant memories into context
- **Organizes by topic** — Collections group memories semantically (e.g. `architecture`, `debugging`, `project-notes`)
- **Searches semantically** — Find memories by meaning, not just keywords
- **Runs locally** — ChromaDB + Ollama bge-m3. No API keys, no cloud, no data leaving your machine

## Architecture

```
┌──────────────────────────────────┐
│  Claude Code                     │
│  ┌────────────────────────────┐  │
│  │  MCP Tools                 │  │  memory_store, memory_find, etc.
│  │  Auto-retrieval Hook       │  │  fires every message
│  └────────────┬───────────────┘  │
├───────────────┼──────────────────┤
│  Ember Memory │                  │
│  ┌────────────┴───────────────┐  │
│  │  Embedding Layer           │  │  Ollama bge-m3 (swappable)
│  ├────────────────────────────┤  │
│  │  Storage Backend           │  │  ChromaDB (swappable)
│  └────────────────────────────┘  │
└──────────────────────────────────┘
```

## Prerequisites

- **Python 3.10+**
- **Ollama** — [Install here](https://ollama.com)
- **Claude Code** — Anthropic's CLI for Claude

## Quickstart

### 1. Clone and install

```bash
git clone https://github.com/kindled-flame/ember-memory.git
cd ember-memory
pip install chromadb mcp[cli]
```

### 2. Set up Ollama

```bash
ollama serve        # Start Ollama (if not already running)
ollama pull bge-m3  # Download the embedding model
```

### 3. Run setup

```bash
python scripts/setup.py
```

This will:
- Verify all prerequisites
- Create the data directory (`~/.ember-memory`)
- Register the MCP server with Claude Code
- Wire the auto-retrieval hook

### 4. Restart Claude Code

Close and reopen Claude Code to load the MCP server.

### 5. Ingest your content

```bash
# Ingest a directory of markdown/text files
python -m ember_memory.ingest /path/to/your/docs

# Into a specific collection
python -m ember_memory.ingest /path/to/notes --collection project-notes

# Only process new/changed files
python -m ember_memory.ingest /path/to/docs --sync
```

### 6. Start chatting

That's it. Memories automatically appear in context when relevant. You can also use the MCP tools directly:

- **"Remember that we decided to use PostgreSQL for the user service"** — your AI partner calls `memory_store`
- **"What do we know about the auth system?"** — `memory_find` searches semantically
- **"List my memory collections"** — `list_collections` shows what's stored

## MCP Tools

| Tool | Description |
|------|-------------|
| `memory_store` | Save a memory with optional tags and source |
| `memory_find` | Semantic search across one or all collections |
| `memory_update` | Update existing memory (preserves metadata) |
| `memory_delete` | Remove a memory by ID |
| `list_collections` | Show all collections and entry counts |
| `create_collection` | Create a new topic collection |
| `delete_collection` | Remove a collection (requires confirmation) |
| `collection_stats` | View stats and sample entries |

## Auto-Retrieval Hook

The hook fires on every `UserPromptSubmit` event:

1. Takes your message text
2. Searches all collections via bge-m3 embeddings
3. Filters by similarity threshold (default: 0.45)
4. Injects the top results into context as `<ember-memory>` tags

Your AI partner sees relevant memories without you asking. It just knows.

## Configuration

All settings via environment variables — no config files to manage:

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBER_BACKEND` | `chromadb` | Storage backend |
| `EMBER_DATA_DIR` | `~/.ember-memory` | Where data is stored |
| `EMBER_EMBEDDING_PROVIDER` | `ollama` | Embedding provider |
| `EMBER_EMBEDDING_MODEL` | `bge-m3` | Embedding model name |
| `EMBER_OLLAMA_URL` | `http://localhost:11434/api/embeddings` | Ollama endpoint |
| `EMBER_DEFAULT_COLLECTION` | `general` | Default collection name |
| `EMBER_SEARCH_LIMIT` | `10` | Max results for tool searches |
| `EMBER_SIMILARITY_THRESHOLD` | `0.45` | Min similarity for auto-retrieval |
| `EMBER_MAX_HOOK_RESULTS` | `5` | Max results injected per message |
| `EMBER_MAX_PREVIEW_CHARS` | `800` | Max chars per memory in hook output |
| `EMBER_HOOK_DEBUG` | `false` | Enable hook debug logging |
| `EMBER_CONTEXT_TAG` | `ember-memory` | XML tag name for injected context |

## Ingestion

The ingestion pipeline chunks markdown files by headers and stores them with content-hash IDs (so re-ingesting won't duplicate).

```bash
# Ingest everything in a directory
python -m ember_memory.ingest ./my-docs

# Files in subdirectories auto-map to collections by folder name
# my-docs/
#   architecture/    → collection: "architecture"
#   debugging/       → collection: "debugging"
#   notes.md         → collection: "general"

# Force all files into one collection
python -m ember_memory.ingest ./my-docs --collection my-project

# Sync mode — only re-process changed files
python -m ember_memory.ingest ./my-docs --sync

# Rebuild a collection from scratch
python -m ember_memory.ingest --rebuild my-collection
```

## Adding More Backends

Ember Memory is designed for multiple storage backends. To add one:

1. Create `ember_memory/backends/your_backend.py`
2. Implement the `MemoryBackend` abstract class (see `base.py`)
3. Register it in `loader.py`

The embedding layer is also swappable — same pattern in `ember_memory/embeddings/`.

**Planned backends:**
- Qdrant (for users who want a dedicated vector DB)

## Project Structure

```
ember-memory/
  ember_memory/
    __init__.py          # Package + version
    config.py            # All configuration (env vars)
    server.py            # MCP server (the tools)
    hook.py              # Auto-retrieval hook
    ingest.py            # Ingestion pipeline
    backends/
      base.py            # Abstract backend interface
      chromadb_backend.py  # ChromaDB implementation
      loader.py          # Backend factory
    embeddings/
      loader.py          # Embedding function factory
  scripts/
    setup.py             # Interactive setup script
  README.md
```

## Why "Ember"?

A flame that persists. Memory that carries forward. Built by [Kindled Flame Studios](https://kindledflamestudios.com) — because every AI deserves to remember.

## License

MIT
