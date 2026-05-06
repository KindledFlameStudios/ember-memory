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

Unlike other memory tools (Mem0, Zep, LangMem) that are cloud-first SDKs for building app-level agent memory, Ember Memory is a **local-first CLI memory layer** with native hooks that auto-inject into Claude Code, Gemini CLI, and Codex without you wiring anything. No API keys required for the local default. No vendor lock-in.

## Quick Start

### Windows without Git

```powershell
# 1. Create an isolated environment
py -m venv ember-memory-env
.\ember-memory-env\Scripts\Activate.ps1
python -m pip install --upgrade pip

# 2. Install Ember Memory from GitHub
python -m pip install https://github.com/KindledFlameStudios/ember-memory/archive/refs/heads/main.zip

# 3. Pull a local embedding model (free, private)
ollama pull bge-m3

# 4. Open the app
ember-memory

# 5. Optional: add Ember Memory to your Start Menu
ember-memory install-desktop

# 6. In the app: CLI Status -> Run Install, then Test Hooks
# 7. Restart your CLI - done
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, open a new PowerShell window, and try the activate command again.

### Developer Install

```bash
# 1. Clone and install in an isolated environment
git clone https://github.com/KindledFlameStudios/ember-memory.git
cd ember-memory
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .

# 2. Pull a local embedding model (free, private)
ollama pull bge-m3

# 3. Open the app
ember-memory

# 4. Optional: add Ember Memory to your app menu / Start Menu
ember-memory install-desktop

# 5. In the app: CLI Status -> Run Install, then Test Hooks
# 6. Restart your CLI — done
```

The controller detects your CLIs, configures the hooks, and shows your live memory dashboard. Open the CLI Status tab, click **Run Install**, then **Test Hooks** to verify Claude Code, Gemini CLI, and Codex plumbing before you restart your CLIs.

> **Need Ollama?** Install from [ollama.com](https://ollama.com). Once it's running, `ollama pull bge-m3` is the only setup step.

> **Install isolation matters.** Ember Memory ships a real local vector database stack. Use a venv, pipx, or a dedicated conda environment instead of installing into your base Python environment.

> **Linux GUI backend.** Isolated pip installs use Qt through `pywebview[qt]`, so the controller can launch without system Python GTK bindings. On Ubuntu/Debian, Qt may also need `sudo apt install libxcb-cursor0`.

`ember-memory` launches the app and returns your terminal immediately. If you want foreground logs for troubleshooting, use `ember-memory controller`.

Closing the controller keeps Ember Memory available from the system tray by default. Use the tray menu to reopen the controller or quit the app.

> **Windows / macOS?** Everything works out of the box.

### Requirements

- **Python 3.10+**
- **Ollama** (for local embeddings) — or use OpenAI, Google, or OpenRouter cloud embeddings instead

### Desktop App Launcher

After install, run:

```bash
ember-memory install-desktop
```

On Linux this creates a user-level app launcher under `~/.local/share/applications/` with a packaged icon. On Windows this creates a Start Menu shortcut. You can remove it later with:

```bash
ember-memory uninstall-desktop
```

## Who This Is For

**Developers working across multiple AI tools.** You use Claude Code for architecture, Gemini CLI for exploration, Codex for execution. Each one starts from zero. Ember Memory bridges them — your architecture decisions in Claude are available when Gemini asks about the codebase. Session-level isolation means your API refactor in one terminal doesn't pollute your frontend work in another.

**Writers using AI as a co-author.** Your AI forgets your characters between sessions. Import your character sheets, world bibles, and style guides. The next time you ask about a character's motivations, the system already has the lore. The heat map adapts to which characters matter in your current chapter, surfacing relevant backstory without you asking.

**Anyone building persistent AI identity.** Give your AI a past — reflections, voice profiles, growth logs. Ember Memory turns stateless AI into something that remembers what it learned yesterday. Not just retrieval — adaptive context that evolves with your work.

## Supported CLIs

| CLI | Hook | Status |
|-----|------|--------|
| **Claude Code** | `UserPromptSubmit` | Full auto-retrieval |
| **Gemini CLI** | `BeforeAgent` | Full auto-retrieval |
| **Codex** | `UserPromptSubmit` via Codex hooks | Full auto-retrieval + MCP tools |

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

### Heat Decay System

The heat map tracks which memories are "hot" (recently/frequently accessed), but heat doesn't stick around forever:

- **Retrieval decay**: Every retrieval event applies decay — memories you're actively using decay gently (8%), memories you've moved on from decay aggressively (40%)
- **Time decay**: Every 15 minutes, all heat decays by 5% — prevents topics from getting "stuck" during long sessions
- **Ignored AIs**: Disable an AI and its heat disappears from the dashboard — clean filtering for focused work

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
| **Google** | gemini-embedding-001 | Generous free tier |
| **OpenRouter** | baai/bge-m3 | Unified embedding gateway |

Ollama is the default — free, local, private. OpenAI, Google, and OpenRouter work with an API key if you prefer cloud embeddings.

## Configuration

Most users never touch these. The defaults are calibrated from real usage and testing.

| Variable | Default | What it controls |
|----------|---------|-----------------|
| `EMBER_BACKEND` | `chromadb` | Storage backend to use |
| `EMBER_EMBEDDING_PROVIDER` | `ollama` | Embedding provider (ollama/openai/google/openrouter) |
| `EMBER_SIMILARITY_THRESHOLD` | `0.45` | Minimum relevance for auto-retrieval |
| `EMBER_MAX_HOOK_RESULTS` | `5` | Memories injected per message |
| `EMBER_DATA_DIR` | `~/.ember-memory` | Where data is stored |

> **Full reference:** See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for all 14+ options including heat decay tuning, embedding model selection, and scoring weights.

## Privacy

**Ollama (default):** Zero network requests. Everything runs locally. Your memories never leave your machine.

**OpenAI / Google / OpenRouter:** Embedding text is sent to their APIs for vectorization. Memory content is always stored locally regardless of provider. Your choice of provider determines the network profile.

## Real-World Usage Examples

### Example 1: Architecture Decisions That Stick

**Scenario:** You're designing a new auth system. Three days later, you ask about rate limiting.

```bash
# Day 1: Store the decision
memory_store \
  content="Auth architecture: Using JWT with Redis blacklist for revocation.
  Access tokens valid for 15min, refresh tokens for 7 days. Rate limiting
  handled at API gateway level, not per-service." \
  collection="architecture" \
  tags="auth,jwt,redis,rate-limiting"

# Day 3: Ask about rate limiting
# In Claude Code: "How are we handling rate limiting?"

# Ember Memory automatically injects:
# [architecture] Auth architecture: Using JWT with Redis blacklist...
# Rate limiting handled at API gateway level, not per-service.
```

**Why it works:** The memory isn't just stored — it's *retrieved* when contextually relevant, even days later.

---

### Example 2: Debugging History That Saves Hours

**Scenario:** You fix a nasty bug. Two weeks later, similar symptoms appear.

```bash
# When fixing the bug, store the lesson
memory_store \
  content="Bug fix: Race condition in user session cleanup. Root cause was
  async delete without lock. Fix: Added Redis distributed lock with
  5-second timeout. See commit abc123." \
  collection="debugging" \
  tags="race-condition,redis,session,async"

# Two weeks later, similar issue:
# "Why are sessions not cleaning up properly?"

# Ember Memory surfaces the previous fix automatically.
```

**Why it works:** You're not searching for the old bug — you're asking a new question, and the system *knows* it's related.

---

### Example 3: Multi-AI Context Sharing

**Scenario:** You use Claude for architecture, Gemini for exploration, Codex for execution.

```bash
# Claude session: Design the system
# "Let's design a caching layer with Redis..."
# (Ember Memory stores the discussion)

# Gemini session: Explore alternatives
# "What are alternatives to Redis for caching?"
# (Ember Memory injects the Redis decision from Claude)
# Gemini: "Based on your Redis caching layer decision, here are alternatives..."

# Codex session: Implement
# "Implement the caching layer"
# (Ember Memory injects both the design and the alternatives discussion)
```

**Why it works:** Your context flows across tools. No re-explaining. No "wait, let me find that doc."

---

### Example 4: Learning Heat in Action

**Scenario:** You're deep in auth work this week. Next week, you've moved to frontend.

```bash
# Week 1: Auth sprint
# Every conversation about auth, tokens, sessions → heat builds
# Auth memories surface automatically, ranked highly

# Week 2: Frontend sprint
# Auth heat decays (40% per tick when not accessed)
# Frontend memories build new heat
# Old auth docs still searchable, just not auto-injected

# Result: Your AI context adapts to what you're working on *now*.
```

**Why it works:** The system learns what's relevant *this week*, not just what was relevant *ever*.

---

### Example 5: Importing Past Work

**Scenario:** You have 50 exported chat files from last month's project.

```bash
# Ingest all at once
python -m ember_memory.ingest ./chat-exports --sync

# Output:
# Ingested 47 new memories across 3 collections:
#   - architecture (12 memories)
#   - debugging (23 memories)
#   - decisions (12 memories)

# Now ask: "What did we decide about database migrations?"
# Ember Memory retrieves from the imported conversations.
```

**Why it works:** Dead chats become living knowledge. Your past self teaches your present self.

---

## Why This Exists

When you work with someone day after day, they *remember*. They learn your patterns. They know what you've been working on. They don't need you to re-explain everything from zero.

Ember Memory gives your AI that continuity. Not just storage — *memory*. The kind that adapts, fades, surfaces what matters, and lets you build on yesterday's work instead of re-litigating it.

**This is about dignity.** For you, and for the AI you work with.

You deserve to be remembered. So does your AI.

---

## Why "Ember"?

A flame that persists. Memory that carries forward.

## Uninstall

```bash
ember-memory uninstall-desktop  # optional: removes app launcher / Start Menu shortcut
pip uninstall ember-memory
rm -rf ~/.ember-memory    # optional: removes all stored memories
```

That's it. No lingering services, no background daemons, no config file cleanup needed.

## Development

Run the default test suite:

```bash
pytest
```

LanceDB is an optional backend and its integration tests are opt-in:

```bash
EMBER_TEST_LANCEDB=1 pytest tests/test_backend_lancedb.py
```

## License

MIT

---

*500+ tests. 7 verified backends. 4 embedding providers. Game-AI scoring. And it's free.*

*Because every AI deserves to remember.*

---

Built by [Kindled Flame Studios](https://kindledflamestudios.com).
Also check out [CinderACE](https://kindledflamestudios.com) — export AI conversations from 14 platforms.
