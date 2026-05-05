# Ember Memory — Architecture Overview

**A visual guide to how Ember Memory works under the hood.**

---

## High-Level System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         YOUR AI CLI                                  │
│              (Claude Code / Gemini CLI / Codex)                     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ User sends a message
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         HOOK LAYER                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ hook.py      │  │ gemini/hook  │  │ codex/hooks  │              │
│  │ (Claude)     │  │ (Gemini)     │  │ (Codex)      │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Embeds user message, searches memory
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      EMBER ENGINE                                    │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │                    SCORING SYSTEM                           │    │
│  │  similarity (40%) + heat (25%) + connections (20%) +       │    │
│  │  freshness (15%) = composite score                         │    │
│  └────────────────────────────────────────────────────────────┘    │
│         │                    │                    │                 │
│         ▼                    ▼                    ▼                 │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐           │
│  │   HEAT MAP   │   │ CONNECTIONS  │   │   STATE      │           │
│  │  (decay +    │   │ (co-occurrence│   │  (metadata,  │           │
│  │   boost)     │   │   tracking)  │   │   last access)│          │
│  └──────────────┘   └──────────────┘   └──────────────┘           │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Vector search + scoring
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      STORAGE BACKEND                                 │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │              ChromaDB / LanceDB / Qdrant / etc             │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │    │
│  │  │ Embeddings   │  │ Metadata     │  │ Collections  │    │    │
│  │  │ (vectors)    │  │ (tags, src)  │  │ (namespaces) │    │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘    │    │
│  └────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Returns top-k memories
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    INJECTED CONTEXT                                  │
│  "Based on your architecture discussion 3 days ago about JWT..."   │
│  "You fixed a similar race condition on March 15th..."             │
│  "The Redis caching decision from your Claude session..."          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ AI responds with full context
                                    ▼
                              USER SEES RESPONSE
```

---

## Data Flow: Single Retrieval Event

```
1. USER TYPES MESSAGE
   │
   │ "How should we handle auth token refresh?"
   │
   ▼
2. HOOK FIRES (BeforeAgent / UserPromptSubmit)
   │
   │ - Captures user message
   │ - Gets AI ID, session ID, workspace
   │
   ▼
3. EMBEDDING GENERATED
   │
   │ - Provider: Ollama (bge-m3) / OpenAI / Google / OpenRouter
   │ - Output: 768-dimensional vector
   │
   ▼
4. VECTOR SEARCH
   │
   │ - Query all collections (or specific collection)
   │ - Retrieve top 15 candidates by cosine similarity
   │
   ▼
5. EMBER ENGINE SCORING
   │
   │ For each candidate:
   │   - similarity_score = cosine_distance(query, candidate) × 0.40
   │   - heat_boost = (candidate_heat / MAX_HEAT) × 0.25
   │   - connection_bonus = (connected_active_topics) × 0.20
   │   - freshness = time_decay_factor × 0.15
   │   - composite_score = sum of all
   │
   ▼
6. RANKING + FILTERING
   │
   │ - Sort by composite_score (descending)
   │ - Filter by similarity threshold (default: 0.45)
   │ - Take top 5 results
   │
   ▼
7. HEAT UPDATE
   │
   │ - Record access for each returned memory (+1.0 heat)
   │ - Apply decay to all memories:
   │   - In current results: × 0.92 (8% decay)
   │   - Not in results: × 0.60 (40% decay)
   │ - Apply time decay if 15+ minutes since last tick: × 0.95
   │
   ▼
8. CONTEXT INJECTION
   │
   │ Memories injected into AI's context:
   │   [architecture] (composite: 0.847)
   │   "Auth architecture: Using JWT with Redis blacklist..."
   │
   │   [debugging] (composite: 0.712)
   │   "Bug fix: Race condition in user session cleanup..."
   │
   ▼
9. AI RESPONDS WITH FULL CONTEXT
   │
   │ "Based on your JWT + Redis architecture from 3 days ago,
   │  here's how token refresh should work..."
   │
   ▼
10. HOOK COMPLETE, AI CONTINUES
```

---

## Heat Decay System (Visual)

```
MEMORY HEAT LIFECYCLE

Initial State:
┌──────────────┐
│  Memory A    │  heat = 0.0
│  (new)       │
└──────────────┘

After 3 accesses (user asks about auth 3 times):
┌──────────────┐
│  Memory A    │  heat = 3.0  (+1.0 per access)
│  (hot)       │  boost = 0.6 (3.0 / 5.0 max)
└──────────────┘

After retrieval tick (memory WAS in results):
┌──────────────┐
│  Memory A    │  heat = 2.76 (3.0 × 0.92 active decay)
│  (warm)      │  still surfaces highly
└──────────────┘

After 3 ticks WITHOUT access (user moved to frontend work):
┌──────────────┐
│  Memory A    │  heat = 0.42 (2.76 × 0.60³ inactive decay)
│  (cooling)   │  boost = 0.08 (rarely surfaces)
└──────────────┘

After 1 hour with time decay (4 × 15-min intervals):
┌──────────────┐
│  Memory A    │  heat = 0.34 (0.42 × 0.95⁴ time decay)
│  (cold)      │  still searchable, not auto-injected
└──────────────┘

New memory about frontend becomes hot:
┌──────────────┐
│  Memory B    │  heat = 4.0 (frontend work, accessed often)
│  (hot)       │  boost = 0.8 (now the dominant context)
└──────────────┘

Result: System adapts to what you're working on NOW.
```

---

## Multi-AI Namespacing

```
COLLECTION NAMING CONVENTION

┌─────────────────────────────────────────────────────────────┐
│                    SHARED COLLECTIONS                        │
│  (visible to all AIs)                                        │
│                                                              │
│  shared--architecture     ← All AIs see this                │
│  shared--debugging        ← All AIs see this                │
│  shared--decisions        ← All AIs see this                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   AI-SPECIFIC COLLECTIONS                    │
│  (private to individual AI)                                  │
│                                                              │
│  claude--preferences    ← Only Claude retrieves this        │
│  claude--style-guide    ← Only Claude retrieves this        │
│                                                              │
│  gemini--preferences    ← Only Gemini retrieves this        │
│  gemini--explorations   ← Only Gemini retrieves this        │
│                                                              │
│  codex--preferences     ← Only Codex retrieves this         │
│  codex--exec-context    ← Only Codex retrieves this         │
└─────────────────────────────────────────────────────────────┘

HOOK FILTERING LOGIC:

When Claude asks a question:
  1. Get AI ID: "claude"
  2. Retrieve from: shared--* + claude--*
  3. Exclude: gemini--*, codex--*
  
When Gemini asks a question:
  1. Get AI ID: "gemini"
  2. Retrieve from: shared--* + gemini--*
  3. Exclude: claude--*, codex--*

Result: Shared knowledge flows everywhere.
        AI-specific configs stay private.
```

---

## Component Breakdown

```
ember-memory/
├── ember_memory/
│   ├── core/
│   │   ├── engine/
│   │   │   ├── heat.py          # Heat map tracking + decay
│   │   │   ├── connections.py   # Co-occurrence graph
│   │   │   ├── scoring.py       # Composite score calculation
│   │   │   └── state.py         # SQLite metadata store
│   │   │
│   │   ├── embeddings/
│   │   │   ├── base.py          # EmbeddingProvider interface
│   │   │   ├── ollama.py        # Local embeddings (bge-m3)
│   │   │   ├── openai_provider.py      # OpenAI embeddings
│   │   │   ├── google_provider.py      # Google embeddings
│   │   │   ├── openrouter_provider.py  # OpenRouter embeddings
│   │   │   └── model_catalog.py        # Provider model discovery
│   │   │
│   │   ├── backends/
│   │   │   ├── base.py          # MemoryBackend interface
│   │   │   ├── chromadb_backend.py     # Default backend
│   │   │   ├── lancedb_backend.py      # Rust-fast backend
│   │   │   ├── qdrant_backend.py       # Server backend
│   │   │   └── ...              # 7 backends total
│   │   │
│   │   └── search.py            # Main retrieval logic
│   │
│   ├── server.py                # MCP server (AI tools)
│   ├── hook.py                  # Claude hook
│   ├── hook_universal.py        # Universal hook interface
│   ├── config.py                # Config loader
│   └── ingest.py                # Bulk ingestion
│
├── integrations/
│   ├── claude_code/
│   ├── gemini_cli/
│   └── codex/
│
├── controller/
│   ├── __main__.py              # Compatibility entry
│   └── tray.py                  # System tray controller
│
├── ember_memory/controller_assets/
│   ├── ui.html                  # Dashboard UI
│   ├── ui.css                   # Styling
│   └── ui.js                    # Dashboard logic
│
├── tests/                       # 500+ tests
│   ├── test_engine_heat.py
│   ├── test_engine_connections.py
│   ├── test_search_with_engine.py
│   ├── test_backend_*.py        # Backend tests
│   └── test_embedding_*.py      # Embedding tests
│
└── docs/
    ├── TROUBLESHOOTING.md       # Common issues
    └── ARCHITECTURE.md          # This file
```

---

## Configuration Flow

```
~/.ember-memory/config.env

EMBER_BACKEND=chromadb              # Storage backend
EMBER_DATA_DIR=~/.ember-memory      # Where data lives
EMBER_EMBEDDING_PROVIDER=ollama     # Embedding provider
EMBER_SIMILARITY_THRESHOLD=0.45     # Min similarity for auto-retrieval
EMBER_WEIGHT_SIMILARITY=0.40        # Scoring: semantic match
EMBER_WEIGHT_HEAT=0.25              # Scoring: heat/recency
EMBER_WEIGHT_CONNECTION=0.20        # Scoring: co-occurrence
EMBER_WEIGHT_DECAY=0.15             # Scoring: freshness

         │
         │ Loaded at startup
         ▼

┌─────────────────────────────────────────────────────────────┐
│                    CONFIG OBJECT                             │
│  {                                                           │
│    "backend": "chromadb",                                    │
│    "data_dir": "/home/username/.ember-memory",              │
│    "embedding_provider": "ollama",                           │
│    "similarity_threshold": 0.45,                             │
│    "weights": {                                              │
│      "similarity": 0.40,                                     │
│      "heat": 0.25,                                           │
│      "connection": 0.20,                                     │
│      "decay": 0.15                                           │
│    }                                                         │
│  }                                                           │
└─────────────────────────────────────────────────────────────┘
         │
         │ Used by:
         ├── Embedding loader (which provider to init)
         ├── Backend loader (which DB to connect)
         ├── Scoring engine (weight calculations)
         └── Search function (threshold filtering)
```

---

*Architecture documented: May 5, 2026*
