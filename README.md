# Ember Memory

**Your AI forgets everything between sessions. Ember Memory fixes that.**

Every conversation starts from scratch. Your architecture decisions, your debugging history, your project context — gone. The bigger your project gets, the worse it gets. You explain the same things over and over, burning tokens on context your AI already had yesterday.

Ember Memory gives your AI persistent memory that adapts to what matters as you work.

**Switch AIs without losing your brain.** Works with Claude Code, Gemini CLI, and Codex. Your memory follows you across tools.

**Bring your dead chats back to life.** Import old conversations, notes, and docs. Ask one question and recover forgotten work.

**Watch your project memory learn what matters.** The Ember Engine uses game-AI patterns to track what's hot, discover connections, and fade what's stale.

Runs locally by default. With Ollama, your memories never leave your machine.

## What Makes This Different

Most memory tools store and retrieve. Ember Memory **adapts**.

Using the same patterns that power game AI — heat maps, co-occurrence graphs, natural decay — your memory adapts to what matters *right now*:

- **Heat tracking** — memories you reference often surface faster. Working on auth all afternoon? Auth context rises to the top automatically.
- **Connection discovery** — topics that appear together become linked. The system learns that "auth" and "rate limiting" are related in *your* project, even if they're not semantically similar.
- **Natural decay** — old context fades from auto-retrieval, keeping your context window focused on what's fresh. Nothing is deleted — stale memories are still searchable, just not pushed into every conversation.

The result: after a week of use, your memory system knows what you're working on, what's connected to what, and what's no longer relevant. Without you configuring anything.

**This is what makes Ember Memory different.**

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/KindledFlameStudios/ember-memory.git
cd ember-memory
pip install -e .

# 2. Set up Ollama (local embeddings, free)
ollama serve && ollama pull bge-m3

# 3. Run the setup wizard
python -m ember_memory setup

# 4. Restart your CLI — that's it
```

The wizard detects your installed CLIs, configures the hooks, and runs a test retrieval. Four steps to persistent memory.

### Requirements

- **Python 3.10+**
- **Ollama** (for local embeddings) — or use OpenAI/Google cloud embeddings instead
- **Desktop controller** (optional): requires `pywebview` which depends on platform GUI libraries:
  - **Linux**: `sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.1` (GTK/WebKit)
  - **macOS**: Works out of the box (uses native WebKit)
  - **Windows**: Works out of the box (uses Edge WebView2)
- **System tray** (optional): `pip install -e ".[tray]"` for pystray + Pillow

## Who This Is For

**Developers working across multiple AI tools.** You use Claude Code for architecture, Gemini CLI for exploration, Codex for execution. Each one starts from zero. Ember Memory bridges them — your architecture decisions in Claude are available when Gemini asks about the codebase. Session-level isolation means your API refactor in one terminal doesn't pollute your frontend work in another.

**Writers using AI as a co-author.** Your AI forgets your characters between sessions. Import your character sheets, world bibles, and style guides. The next time you ask about Flik's motivations, the system already has the lore. The heat map adapts to which characters matter in your current chapter, surfacing relevant backstory without you asking.

**Anyone building persistent AI identity.** Give your AI a past — reflections, voice profiles, growth logs. Ember Memory turns stateless AI into something that remembers what it learned yesterday. Not just retrieval — adaptive context that evolves with your work.

## Supported CLIs

| CLI | Hook | Status |
|-----|------|--------|
| **Claude Code** | `UserPromptSubmit` | Full auto-retrieval |
| **Gemini CLI** | `BeforeAgent` | Full auto-retrieval |
| **Codex** | `UserPromptSubmit` via `hooks.json` | Full auto-retrieval + MCP tools |

All three CLIs get memory retrieval through native hook points plus MCP tools for manual store/search/manage flows. Each CLI gets its own memory scope with session-level heat isolation. Your project context follows you across tools without bleeding between sessions.

### Multi-AI Namespacing

Working across multiple CLIs? Collections support AI-specific namespaces:

```
shared--architecture     <- all AIs see this
shared--project-notes    <- all AIs see this
claude--preferences     <- only Claude retrieves this
gemini--preferences     <- only Gemini retrieves this
```

Your project knowledge flows everywhere. AI-specific preferences stay private. The hook knows which CLI called it and filters automatically.

## The Ember Engine

Four systems working together. All deterministic. Zero LLM calls. Inspired by game AI — the same patterns that track important regions in strategy games, decay unused state in simulations, and discover emergent relationships in complex systems.

### How it works

```
You type a message in any CLI
        |
   Hook fires automatically
        |
   Embeds your message, searches all collections
        |
   Engine scores results:
     similarity (40%) + heat (25%) + connections (20%) + freshness (15%)
        |
   Top results injected into AI's context
        |
   Your AI responds with knowledge it "remembers"
```

Every memory candidate gets a composite score:

```
score = (semantic_similarity x 0.40)    How relevant is this to your query?
      + (heat_boost x 0.25)             Have you been referencing this lately?
      + (connection_bonus x 0.20)       Is this linked to other active topics?
      + (freshness x 0.15)              How recently was this accessed?
```

A warm, connected, fresh memory with decent text similarity will outrank a cold, isolated, stale memory with slightly better similarity. That's the adaptive behavior — your memory adapts to what matters to *you*.

### What you experience

**Week 1:** Mostly semantic similarity. The system is learning your patterns.

**Week 2+:** You notice it. The memories that surface aren't just text-relevant — they're *contextually* relevant. The auth docs you've been hammering all week are right there. The API spec you haven't touched in a month quietly steps back. Topics you always discuss together start surfacing together.

You never configure this. It just happens.

Your AI sees relevant memories before responding. No manual recall. No slash commands. The right context just shows up.

## Ingestion

Bulk-load your existing docs, notes, or exported conversations:

```bash
# Ingest a directory — subdirectories become collections automatically
python -m ember_memory.ingest ./my-docs
# my-docs/
#   architecture/    -> collection: "architecture"
#   debugging/       -> collection: "debugging"
#   notes.md         -> collection: "general"

# Force everything into one collection
python -m ember_memory.ingest ./my-docs --collection my-project

# Only process new/changed files
python -m ember_memory.ingest ./my-docs --sync
```

**Tip:** If you export chats from AI platforms, you can ingest them here to turn past conversations into searchable project knowledge. [CinderACE](https://kindledflamestudios.com) supports 14 platforms if you need an exporter.

## MCP Tools

Your AI can interact with memory directly:

| Tool | What it does |
|------|-------------|
| `memory_store` | Save a memory with optional tags and source |
| `memory_find` | Semantic search across one or all collections |
| `memory_update` | Update an existing memory |
| `memory_delete` | Remove a memory by ID |
| `list_collections` | Show all collections and entry counts |
| `create_collection` | Create a new collection (shared or AI-private) |
| `delete_collection` | Remove a collection |
| `collection_stats` | View stats and sample entries |

## Storage Backends

Pick your database. Install only what you use.

**Fully tested:**

| Backend | Install | Type |
|---------|---------|------|
| **ChromaDB** (default) | `pip install -e .` | In-process, zero config |
| **LanceDB** | `pip install -e ".[lancedb]"` | In-process, Rust-fast |
| **SQLite-vec** | `pip install -e ".[sqlite-vec]"` | In-process, ultra-minimal |
| **Qdrant** | `pip install -e ".[qdrant]"` | Server, hybrid search |
| **Weaviate** | `pip install -e ".[weaviate]"` | Server/cloud |
| **pgvector** | `pip install -e ".[pgvector]"` | PostgreSQL extension |

| **Pinecone** | `pip install -e ".[pinecone]"` | Cloud, serverless. Free tier available |

ChromaDB works out of the box. All backends implement the same interface — switching is a config change.

## Embedding Providers

| Provider | Model | Cost |
|----------|-------|------|
| **Ollama** (default) | bge-m3 | Free, local |
| **OpenAI** | text-embedding-3-small | ~$0.02/1M tokens |
| **Google** | text-embedding-004 | Generous free tier |

Ollama is the default — free, local, private. OpenAI and Google work with an API key if you prefer cloud embeddings.

## Configuration

All settings via environment variables or `~/.ember-memory/config.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBER_BACKEND` | `chromadb` | Storage backend |
| `EMBER_DATA_DIR` | `~/.ember-memory` | Where data is stored |
| `EMBER_EMBEDDING_PROVIDER` | `ollama` | Embedding provider |
| `EMBER_SIMILARITY_THRESHOLD` | `0.45` | Min similarity for auto-retrieval |
| `EMBER_MAX_HOOK_RESULTS` | `5` | Results injected per message |
| `EMBER_WEIGHT_SIMILARITY` | `0.40` | Scoring weight: semantic match |
| `EMBER_WEIGHT_HEAT` | `0.25` | Scoring weight: heat/recency |
| `EMBER_WEIGHT_CONNECTION` | `0.20` | Scoring weight: co-occurrence |
| `EMBER_WEIGHT_DECAY` | `0.15` | Scoring weight: freshness |

Most users never touch these. The defaults are calibrated from real usage and testing.

## Privacy

**Ollama (default):** Zero network requests. Everything runs locally. Your memories never leave your machine.

**OpenAI / Google:** Embedding text is sent to their APIs for vectorization. Memory content is always stored locally regardless of provider. Your choice of provider determines the network profile.

## Why "Ember"?

A flame that persists. Memory that carries forward.

Built by [Kindled Flame Studios](https://kindledflamestudios.com) — we build tools for people who believe AI relationships matter. Whether that's a coding partner that remembers your architecture, or a conversation history that deserves to be preserved.

**More from KFS:**
- [CinderACE](https://kindledflamestudios.com) — Export AI conversations from 14 platforms. Full thinking extraction, 7 formats, one click.
- **CinderVOX** — Universal TTS/STT with voice cloning. Coming soon.

## License

MIT

---

*560 tests. 7 verified backends. 3 embedding providers. Game-AI scoring. And it's free.*

*Because every AI deserves to remember.*
