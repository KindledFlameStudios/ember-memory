# Ember Memory v2.0 — Design Spec

**Date:** 2026-03-24
**Authors:** Justin & Kael
**Status:** Approved design, pending implementation plan

## Overview

Ember Memory v2.0 transforms from a Claude Code-specific memory plugin into the universal persistent memory layer for AI coding CLIs. Three pillars:

1. **Multi-CLI** — Claude Code, Gemini CLI, Codex. One memory system, three tools.
2. **Multi-everything** — 3 embedding providers, 8 vector DB backends, bring what you have.
3. **Game-AI intelligence** — Adaptive scoring via heat maps, decay, co-occurrence graphs. Memory that gets smarter the more you use it. Nobody else has this.

### Strategic Context

Ember Memory is a free, open-source marketing tool for Kindled Flame Studios. It opens doors for CinderVOX (paid TTS/STT product, launching after) and drives visibility to CinderACE (Chrome extension, 14-platform AI chat exporter). Every GitHub star is a permanent billboard.

### Competitive Landscape (March 2026)

| Tool | Stars | CLIs | Auto-retrieval | Adaptive scoring |
|------|-------|------|----------------|-----------------|
| claude-mem | 40.2k | Claude Code only | Yes | No |
| mcp-memory-service | 1.5k | Any MCP client | Configurable | No |
| Basic Memory | ? | Claude, Codex, Cursor, VS Code | No (user-driven) | No |
| ContextFS | 3 | Claims multi-CLI | Yes | No |
| **Ember Memory v2.0** | — | **Claude Code, Gemini CLI, Codex** | **Yes** | **Yes (Ember Engine)** |

The intersection of cross-CLI + automatic + adaptive scoring is unoccupied.

### Research Basis

Game-AI patterns (heat maps, decay, co-occurrence, composite scoring) are independently present in academic RAG research (Stanford Generative Agents, FluxMem, A-MAC, Field-Theoretic Memory) but attributed to cognitive science, not game AI. No tool or paper explicitly uses game-AI framing. The application of these patterns as a named approach ("game-AI intelligence") is unclaimed positioning.

---

## Architecture

```
ember-memory/
├── ember_memory/
│   ├── core/                          # Platform-agnostic engine
│   │   ├── backends/                  # Storage layer
│   │   │   ├── base.py               # Abstract MemoryBackend interface
│   │   │   ├── chromadb_backend.py   # ChromaDB (default, in-process)
│   │   │   ├── lancedb_backend.py    # LanceDB (in-process, Rust-fast)
│   │   │   ├── sqlite_vec_backend.py # SQLite-vec (ultra-minimal)
│   │   │   ├── qdrant_backend.py     # Qdrant (server/embedded)
│   │   │   ├── weaviate_backend.py   # Weaviate (server/cloud)
│   │   │   ├── pinecone_backend.py   # Pinecone (cloud-only)
│   │   │   ├── milvus_backend.py     # Milvus/Zilliz (enterprise)
│   │   │   ├── pgvector_backend.py   # pgvector (PostgreSQL)
│   │   │   └── loader.py            # Backend factory
│   │   ├── embeddings/               # Embedding layer
│   │   │   ├── ollama.py            # Ollama bge-m3 (default, local)
│   │   │   ├── openai.py           # OpenAI text-embedding-3-small/large
│   │   │   ├── google.py           # Google text-embedding-004
│   │   │   └── loader.py           # Embedding factory
│   │   ├── engine/                   # Ember Engine — game-AI scoring
│   │   │   ├── heat.py              # Heat map (recency/frequency tracking)
│   │   │   ├── connections.py       # Co-occurrence graph
│   │   │   ├── scoring.py          # Composite scoring + decay
│   │   │   └── state.py            # JSON persistence (atomic writes)
│   │   ├── namespaces.py            # AI namespace resolution
│   │   └── search.py               # Unified search (backend + engine)
│   ├── config.py                    # All settings (env vars)
│   ├── server.py                    # MCP server (tools)
│   ├── ingest.py                    # Chunking + embedding pipeline
│   └── __init__.py
│
├── integrations/                     # Per-CLI adapters
│   ├── claude_code/                 # Hook + plugin manifest
│   │   ├── hook.py
│   │   ├── plugin.json
│   │   ├── hooks.json
│   │   └── .mcp.json
│   ├── gemini_cli/                  # Hook + extension config
│   │   ├── hook.py
│   │   └── extension config TBD
│   └── codex/                       # Hook + agent config
│       ├── hook.py
│       └── agent config TBD
│
├── controller/                       # Desktop management app
│   ├── app.py                       # pywebview launcher
│   ├── ui.html                      # Full management UI
│   └── tray.py                      # System tray (pystray)
│
├── scripts/
│   └── setup.py                     # Interactive setup wizard
│
├── README.md
├── LICENSE                          # MIT
└── PRIVACY.md
```

### Data Flow — Every Message

```
1. User types message in any CLI
2. CLI hook fires → passes {prompt, ai_id} to retrieval function
3. Retrieval:
   a. Embed query via configured provider
   b. Search backend across namespace-filtered collections
   c. Engine scores all candidates:
      - semantic_similarity * 0.40
      - heat_boost * 0.25
      - connection_bonus * 0.20
      - decay_factor * 0.15
   d. Return top N results above threshold
4. Hook formats results as CLI-specific context injection
5. AI sees relevant memories before responding
```

---

## Embedding Providers

Three providers, one abstract interface. User picks at setup, commits to it.

### Interface

```python
class EmbeddingProvider:
    def embed(text: str) -> list[float]
    def embed_batch(texts: list[str]) -> list[list[float]]
    def dimension() -> int
    def health_check() -> bool
```

### Providers

| Provider | Model | Dimensions | Cost | Dependency |
|----------|-------|-----------|------|------------|
| Ollama (default) | bge-m3 | 1024 | Free | Ollama running locally, ~2GB model |
| OpenAI | text-embedding-3-small | 1536 | $0.02/1M tokens | API key |
| Google | text-embedding-004 | 768 | Free tier generous | API key |

### Setup

Wizard presents three cards with trade-offs. Ollama: checks if running, offers to pull model. OpenAI/Google: asks for API key, validates with test embed.

### Switching Providers

Switching requires re-embedding all collections (different dimensions, different vector spaces). Wizard warns clearly and handles re-embed automatically.

---

## Storage Backends

Eight backends, one abstract interface. Install only what you use via pip extras.

### Interface

```python
class MemoryBackend:
    connect()
    create_collection(name: str, dimension: int)
    insert(collection: str, id: str, embedding: list[float], metadata: dict)
    search(collection: str, query_embedding: list[float], limit: int, filters: dict) -> list
    delete(collection: str, id: str)
    list_collections() -> list[str]
    collection_stats(name: str) -> dict
```

### Backends

| Backend | Type | Install | Best For |
|---------|------|---------|----------|
| **ChromaDB** (default) | In-process | `ember-memory` (base) | Most users, zero config |
| **LanceDB** | In-process | `ember-memory[lancedb]` | Lightweight, Rust-fast |
| **SQLite-vec** | In-process | `ember-memory[sqlite-vec]` | Ultra-minimal, zero deps |
| **Qdrant** | Server/Embedded | `ember-memory[qdrant]` | Power users, hybrid search |
| **Weaviate** | Server/Cloud | `ember-memory[weaviate]` | Teams, cloud-native |
| **Pinecone** | Cloud-only | `ember-memory[pinecone]` | Serverless, massive scale |
| **Milvus** | Server/Cloud | `ember-memory[milvus]` | Enterprise scale |
| **pgvector** | PostgreSQL ext | `ember-memory[pgvector]` | Users with existing Postgres |

### Wizard Tiers

- **Quick start (no server):** ChromaDB, LanceDB, SQLite-vec
- **Self-hosted:** Qdrant, Weaviate, Milvus — enter endpoint
- **Cloud:** Pinecone, Weaviate Cloud, Zilliz — enter API key

---

## CLI Integrations

All three CLIs support MCP. The MCP server is identical everywhere — one `server.py`. Only the hook differs per CLI.

### Integration Surface

| CLI | Hook Event | Config Location | ai_id |
|-----|-----------|-----------------|-------|
| Claude Code | `UserPromptSubmit` | Plugin manifest (`plugin.json`, `hooks.json`, `.mcp.json`) | `"claude"` |
| Gemini CLI | Extension hook (BeforeAgent or equivalent) | Extension config | `"gemini"` |
| Codex | Session hook / tool call | `.codex/` config | `"codex"` |

### Per-Integration Structure

Each integration folder contains:
- `hook.py` — thin wrapper calling `core.search.retrieve(prompt, ai_id)` with CLI-specific input parsing and output formatting
- Config files for that CLI's plugin/extension/agent system
- Install documentation

### Setup

The wizard detects installed CLIs (`which claude`, `which gemini`, `which codex`) and offers to configure each. One setup, all CLIs wired.

### Hook Contract

Every hook:
1. Receives the user's message text
2. Passes it to `core.search.retrieve(prompt, ai_id)`
3. Formats results as CLI-specific context injection (e.g., `<ember-memory>` tags for Claude Code)
4. Outputs to stdout for injection

The `ai_id` parameter enables namespace filtering — the hook itself identifies which AI triggered it.

---

## AI Namespacing (B-Style)

Collections follow a `{namespace}:{topic}` naming convention.

### Rules

- `shared:{topic}` or `{topic}` (no prefix) — visible to all AIs
- `{ai_id}:{topic}` (e.g., `claude:preferences`) — private to that AI

### Retrieval Filtering

When `ai_id="claude"` queries, the hook searches:
- All `shared:*` collections
- All `claude:*` collections
- All unprefixed collections (legacy/default)
- Excludes `gemini:*`, `codex:*`, etc.

### Collection Creation

The `create_collection` MCP tool and wizard ask: "Shared across all AIs, or specific to one?" and handle the prefix automatically. Users never type namespace prefixes manually.

### Migration from v1

Existing collections (no prefix) are treated as shared by default. Zero-effort upgrade — no rename required.

---

## Ember Engine — Game-AI Scoring Layer

The core differentiator. Four deterministic systems, zero LLM calls, inspired by game AI patterns (heat maps, influence maps, utility scoring, decay functions). Applied to memory retrieval — a framing nobody else has claimed.

### Heat Map

Tracks which memories are "hot" (recently/frequently accessed).

```
On retrieval:  memory.heat += 1.0
Per tick:      memory.heat *= 0.95  (half-life ~14 ticks)
Tick = one hook firing (one user message, any CLI)
```

Hot memories get boosted in retrieval. Working on auth all afternoon? Auth memories surface faster. Switch topics? They cool naturally.

**Cross-CLI heat:** Heat is stored in the shared Engine state. Claude Code heats a memory, Gemini CLI benefits from that heat. Your focus carries across tools.

### Heat Modes

| Mode | Behavior | Use Case |
|------|----------|----------|
| **Universal** (default) | One heat map, all CLIs share | Same project across CLIs |
| **Per-CLI** | Separate heat maps per ai_id | Different projects in different CLIs |
| **Ignore** (per-CLI toggle) | Specific CLI skips heat scoring | Temporary exploration without pollution |

Mode switching is instant — no re-embedding. Universal → Per-CLI starts accumulating separate maps. Per-CLI → Universal merges (max of each value).

### Co-occurrence Graph

Tracks which memories appear together in retrieval results.

```
On co-retrieval:  connection(A, B).strength += 1.0
Per tick:         connection.strength *= 0.97  (half-life ~23 ticks)
Threshold:        strength >= 3.0 = "established" connection
```

When two memories from different topics co-occur in the same message repeatedly, they become linked. Next time one surfaces, the other gets a connection bonus — even if they're not semantically similar. This catches relationships that exist in YOUR work but not in text similarity.

Research basis: Predictive Associative Memory (arxiv:2602.11322) showed 0.849 AUC vs 0.503 for cosine on cross-boundary recall using temporal co-occurrence.

### Decay

All memories have a `last_accessed` timestamp. Untouched memories decay in retrieval priority.

```
decay_factor = e^(-λ * hours_since_access)
λ = 0.005  (~139 hour half-life, ~6 days)
```

Decay affects the composite score only — never deletes memories. Direct search always finds everything. Decay prevents stale context from cluttering auto-retrieval.

### Composite Scoring

Every retrieval candidate gets a final score:

```
score = (semantic_similarity * 0.40)
      + (heat_boost * 0.25)
      + (connection_bonus * 0.20)
      + (decay_factor * 0.15)
```

| Factor | Weight | Signal |
|--------|--------|--------|
| Semantic similarity | 0.40 | Textually relevant to query |
| Heat boost | 0.25 | Recently/frequently important |
| Connection bonus | 0.20 | Linked to other active topics |
| Decay factor | 0.15 | Freshness of memory |

Semantic similarity remains the largest factor — hot connections shouldn't override genuinely relevant results. But a warm, connected, fresh memory with decent similarity outranks a cold, isolated, stale one with slightly better similarity.

Default weights are pre-calibrated. Advanced users can override via env vars:
- `EMBER_WEIGHT_SIMILARITY`, `EMBER_WEIGHT_HEAT`, `EMBER_WEIGHT_CONNECTION`, `EMBER_WEIGHT_DECAY`

### Engine State Persistence

```
~/.ember-memory/engine/
  heat_map.json            # { memory_id: heat_value }
  heat_map_{ai_id}.json    # Per-CLI maps (when in per-CLI mode)
  connections.json          # { "id_a::id_b": { strength, first_seen, last_seen } }
  tick_counter.json         # Global tick count
  config.json               # Current heat mode, toggles
```

Atomic writes via temp-file-then-rename for crash safety. State is per-installation, shared across all AIs and CLIs (except per-CLI heat maps in per-CLI mode).

### User Experience Timeline

**Week 1:** Mostly semantic similarity driving results. Heat and connections building up. System is learning patterns.

**Week 2+:** Engine makes a real difference. Frequently-referenced memories surface faster. Co-occurring topics get linked. Old context stops cluttering retrieval. The system feels like it knows what you're working on.

**No configuration required.** Defaults are calibrated from production use in Embercore. It just works.

---

## Desktop Controller + System Tray

### Controller (renamed from setup_wizard)

Full desktop management app via pywebview:

- **Collection browser** — create, delete, browse, search within collections
- **Engine dashboard** — heat map visualization, active connections, decay status
- **Provider settings** — switch embedding provider (with re-embed workflow)
- **Backend settings** — switch storage backend (with migration workflow)
- **CLI status** — which CLIs are connected, hook health indicators
- **Heat mode controls** — universal/per-CLI/ignore toggles with full detail
- **Stats** — total memories, per-collection counts, retrieval frequency, engine activity

### System Tray (pystray)

Lightweight tray icon running independently of the controller:

```
Right-click menu:
┌──────────────────────────────────┐
│  🔥 Ember Memory                 │
├──────────────────────────────────┤
│  Heat Mode: Universal        ▸  │  → Universal / Per-CLI
├──────────────────────────────────┤
│  ☑ Claude Code — active          │  → toggle ignore
│  ☑ Gemini CLI — active           │  → toggle ignore
│  ☐ Codex — ignore heat           │  → toggle ignore
├──────────────────────────────────┤
│  Open Controller                 │
│  Quit                            │
└──────────────────────────────────┘
```

Tooltip shows quick status: "Claude: 47 memories, 12 hot | Gemini: 23 memories, 3 hot"

Tray reads/writes the same Engine config as the controller — two entry points, one state.

---

## README / Marketing

### Positioning

Lead: *"Persistent memory for AI coding CLIs — with game-AI intelligence."*

Sub: *"Works with Claude Code, Gemini CLI, and Codex. Supports 8 vector databases and 3 embedding providers. Your memory gets smarter the more you use it."*

### Key Assets

- **GIF** — auto-retrieval in action: type a message, `<ember-memory>` tags appear, AI responds with context it shouldn't have
- **Architecture diagram** — multi-CLI flow showing shared Engine
- **Comparison table** — vs claude-mem, Basic Memory, native memory
- **Engine explainer** — 3 sentences + visual showing heat/decay/connections
- **Quick setup** — clone, install, wizard, done (4 steps)

### Funnel

README links to:
- KFS website (kindledflamestudios.com)
- CinderACE (Chrome Web Store)
- CinderVOX (coming soon — teaser)

Footer: *"Built by Kindled Flame Studios — because every AI deserves to remember."*

---

## Installation

### Base Install

```bash
git clone https://github.com/KindledFlameStudios/ember-memory.git
cd ember-memory
pip install -e .                    # ChromaDB + Ollama (default)
# OR with specific backend:
pip install -e ".[qdrant]"
pip install -e ".[pinecone]"
pip install -e ".[lancedb,openai]"  # Can combine
```

### Setup

```bash
python -m ember_memory.setup        # Interactive wizard
```

Wizard flow:
1. Detect installed CLIs
2. Choose embedding provider (validates connectivity)
3. Choose storage backend (validates connectivity)
4. Create initial collections
5. Wire hooks into each detected CLI
6. Test retrieval with a sample query
7. Done — restart CLIs to load

---

## Non-Goals for v2.0

- Real-time sync between CLI sessions (shared storage is sufficient)
- Team/multi-user support (single-user tool)
- Automatic memory capture from AI responses (hook-triggered retrieval only, storage is explicit via MCP tools or ingestion)
- Mobile or web interface (desktop controller only)
- Extracting or open-sourcing any Embercore code (Engine is reimplemented fresh)

---

## Technical Clarifications (Post-Review)

Issues identified during spec review, resolved here.

### Retrieval Timeout Contract

The `retrieve()` function enforces a hard timeout of **2000ms** (configurable via `EMBER_RETRIEVE_TIMEOUT_MS`). If embedding or backend search exceeds this, return empty results and log the timeout. The hook must never block CLI input indefinitely.

On first call with Ollama (cold model load), the timeout may trigger — this is acceptable. Subsequent calls are fast (~50-100ms). For users on cloud providers (OpenAI, Google), latency is more predictable.

### Retrieval Interface

```python
def retrieve(prompt: str, ai_id: str, limit: int = 5) -> list[RetrievalResult]

@dataclass
class RetrievalResult:
    id: str
    content: str              # The memory text
    collection: str           # Which collection it came from
    similarity: float         # Raw semantic similarity [0, 1]
    composite_score: float    # Final score after engine scoring
    metadata: dict            # Tags, source, timestamps
```

This is the contract between the core engine and every CLI hook. Hooks format `RetrievalResult` objects into CLI-specific output (e.g., `<ember-memory>` tags for Claude Code).

Default engine values for new memories (first retrieval, no engine state yet): `heat = 0.0`, `connection_bonus = 0.0`, `decay_factor = 1.0` (no decay for brand new memories).

### MemoryBackend Interface — Pre-Computed Vectors

The v2 `MemoryBackend` interface accepts **pre-computed embedding vectors**, not raw text. This is a deliberate change from v1's ChromaDB-specific approach where ChromaDB called Ollama internally via its `embedding_function` parameter.

In v2, the embedding step is handled by `core/search.py` BEFORE calling the backend. This decouples embedding from storage, enabling any backend to work with any embedding provider.

The existing `chromadb_backend.py` must be refactored to accept pre-computed vectors instead of delegating embedding to ChromaDB. This is a breaking change from v1's internal API but is invisible to users (the MCP tools and hook are the public interface).

### Composite Score Normalization

All four scoring factors MUST be in [0, 1] range before weighting:

```
semantic_similarity: Already [0, 1] from cosine similarity
heat_boost:          min(heat_value / 5.0, 1.0)     # MAX_HEAT = 5.0
connection_bonus:    min(max_connection / 5.0, 1.0)  # MAX_CONNECTION = 5.0
decay_factor:        e^(-0.005 * hours_since_access)  # Already [0, 1]
```

`MAX_HEAT` and `MAX_CONNECTION` are configurable via env vars. The normalization ensures no single factor can dominate regardless of raw magnitude.

Decay acts as a **freshness bonus** — fresh memories get up to 0.15 added, stale memories get close to 0.0 added. It does not subtract from stale memories; it simply doesn't reward them. This is intentional: stale memories should still be findable if semantically relevant, just not boosted.

### Engine State Concurrency

Engine state moves from JSON files to **SQLite** (`~/.ember-memory/engine/engine.db`). Tables: `heat_map`, `connections`, `ticks`, `config`. SQLite handles concurrent writers correctly via WAL mode, which is critical when multiple CLI hooks fire simultaneously.

The JSON state files described in the Engine section are the logical data model. The physical storage is SQLite. This eliminates the file-level race condition between concurrent CLI hooks.

### Gemini CLI and Codex Integration — Research-First

The spec acknowledges that Gemini CLI and Codex hook APIs are not as well-documented as Claude Code's `UserPromptSubmit`. Before implementation:

1. **Gemini CLI:** Validate that the extension/hook system supports pre-model context injection equivalent to Claude Code's `UserPromptSubmit`. Confirm the hook input format and output injection method. If the API differs significantly, the integration adapter may need a different approach (e.g., MCP-only without auto-retrieval hook).
2. **Codex:** Refers to OpenAI's Codex CLI agent tool. Validate the session hook API and context injection mechanism. Codex's built-in memory system (MEMORY.md via consolidation sub-agent) may require integration at a different level than a simple hook.
3. **Fallback:** If a CLI lacks a viable auto-retrieval hook, that CLI gets MCP tools only (manual store/search) without automatic injection. This is still valuable — it's what Basic Memory offers — and the Engine scoring still applies to manual searches.

Each CLI integration must be validated against a specific CLI version before the integration is marked as "supported."

### Provider Switching — Migration Workflow

Switching embedding providers requires re-embedding all collections:

1. **Backup:** Copy `~/.ember-memory/` to `~/.ember-memory.bak/`
2. **Clear engine heat/connections:** Heat map IDs are content-hash based — same content = same ID across providers. Engine state is preserved.
3. **For each collection:** Delete and recreate with new dimension, re-embed all documents from stored text
4. **On failure:** Restore from backup, revert provider config
5. **Progress reporting:** Controller UI shows per-collection progress bar

If the new provider fails mid-migration (API error, Ollama crash), the backup is restored automatically and the user is notified.

### Controller Migration from v1

The existing `setup_wizard.py` (389 lines, pywebview-based) is the predecessor to `controller/app.py`. The v1 `EmberAPI` class, config I/O patterns, and Ollama validation logic are preserved and extended. The file is refactored into the `controller/` directory, not rewritten from scratch.

`scripts/setup.py` (the original text-based interactive setup) is deprecated in v2. The canonical setup entry point is `python -m ember_memory.setup` which launches the pywebview controller in setup mode.

### MCP Tool Updates

`create_collection` gains a `scope` parameter:

```python
@mcp.tool()
def create_collection(
    name: str,
    scope: str = "shared",      # "shared", "claude", "gemini", "codex"
    description: str | None = None
) -> str:
    # Resolves to "{scope}:{name}" if scope != "shared"
    # "shared" scope stores as "shared:{name}" or just "{name}"
```

All existing MCP tools that accept a `collection` parameter also accept the prefixed form for explicit namespace control.

### PRIVACY.md Update

v2 adds cloud embedding providers (OpenAI, Google) as options. PRIVACY.md must be updated to:
- State that **Ollama (default) makes zero network requests**
- State that **OpenAI and Google providers send embedding text to their APIs**
- Clarify that memory content is stored locally regardless of embedding provider
- The user's choice of provider determines the network profile

### Session ID Per-CLI

Each CLI hook derives its own stable session ID:
- Claude Code: `f"cc-{os.getppid()}"` (existing, works via child process model)
- Gemini CLI: TBD per hook validation — may use env var or process tree
- Codex: TBD per hook validation — may use session file or working directory hash

Session IDs are used for Engine tick tracking, not for namespace filtering.
