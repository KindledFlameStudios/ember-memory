# Ember Memory v2.0 — Plan 3: Ember Engine (Game-AI Scoring)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Ember Engine — a game-AI-inspired scoring layer that makes memory retrieval adaptive. Heat maps track what's important right now, co-occurrence graphs discover topic relationships, decay fades stale context, and composite scoring combines all signals with semantic similarity.

**Architecture:** Four deterministic systems (zero LLM calls) stored in a SQLite database for concurrent multi-CLI safety. The Engine hooks into `core/search.py`'s `retrieve()` function — after the backend returns raw similarity results, the Engine re-scores them using heat, connections, and decay before returning to the hook.

**Tech Stack:** Python 3.10+, SQLite (WAL mode), pytest, math (exponential decay)

**Depends on:** Plan 1 (core/search.py, RetrievalResult dataclass)

**Spec:** `docs/superpowers/specs/2026-03-24-ember-memory-v2-design.md` — "Ember Engine" and "Technical Clarifications" sections

---

### Task 1: Engine SQLite State Store

**Files:**
- Create: `ember_memory/core/engine/__init__.py`
- Create: `ember_memory/core/engine/state.py`
- Test: `tests/test_engine_state.py`

The Engine state lives in SQLite (`~/.ember-memory/engine/engine.db`) for concurrent multi-CLI safety. WAL mode handles simultaneous writes from multiple hooks.

- [ ] **Step 1: Create engine directory**

```bash
cd ~/ember-memory
mkdir -p ember_memory/core/engine
touch ember_memory/core/engine/__init__.py
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_engine_state.py
import pytest
from ember_memory.core.engine.state import EngineState


@pytest.fixture
def state(tmp_path):
    return EngineState(db_path=str(tmp_path / "engine.db"))


def test_init_creates_tables(state):
    """EngineState creates all required tables on init."""
    assert state.get_tick() == 0


def test_increment_tick(state):
    state.increment_tick()
    assert state.get_tick() == 1
    state.increment_tick()
    assert state.get_tick() == 2


def test_heat_get_set(state):
    state.set_heat("doc1", 1.5)
    assert state.get_heat("doc1") == pytest.approx(1.5)


def test_heat_default_zero(state):
    assert state.get_heat("nonexistent") == 0.0


def test_heat_increment(state):
    state.increment_heat("doc1", 1.0)
    state.increment_heat("doc1", 1.0)
    assert state.get_heat("doc1") == pytest.approx(2.0)


def test_heat_decay_all(state):
    state.set_heat("doc1", 2.0)
    state.set_heat("doc2", 4.0)
    state.decay_all_heat(factor=0.95)
    assert state.get_heat("doc1") == pytest.approx(1.9)
    assert state.get_heat("doc2") == pytest.approx(3.8)


def test_heat_decay_cleans_near_zero(state):
    state.set_heat("doc1", 0.001)
    state.decay_all_heat(factor=0.95)
    # Values below threshold should be removed
    assert state.get_heat("doc1") == 0.0


def test_connection_get_set(state):
    state.increment_connection("doc1", "doc2", 1.0)
    assert state.get_connection("doc1", "doc2") >= 1.0


def test_connection_symmetric(state):
    """Connection A->B is the same as B->A."""
    state.increment_connection("doc1", "doc2", 1.0)
    assert state.get_connection("doc2", "doc1") >= 1.0


def test_connection_accumulates(state):
    state.increment_connection("a", "b", 1.0)
    state.increment_connection("a", "b", 1.0)
    assert state.get_connection("a", "b") == pytest.approx(2.0)


def test_connection_decay_all(state):
    state.increment_connection("a", "b", 4.0)
    state.decay_all_connections(factor=0.97)
    assert state.get_connection("a", "b") == pytest.approx(3.88)


def test_get_connections_for_id(state):
    state.increment_connection("a", "b", 3.0)
    state.increment_connection("a", "c", 1.0)
    conns = state.get_connections_for("a")
    assert len(conns) == 2


def test_last_accessed_default(state):
    ts = state.get_last_accessed("nonexistent")
    assert ts is None


def test_last_accessed_update(state):
    state.update_last_accessed("doc1")
    ts = state.get_last_accessed("doc1")
    assert ts is not None


def test_heat_mode_default(state):
    assert state.get_config("heat_mode", "universal") == "universal"


def test_heat_mode_set(state):
    state.set_config("heat_mode", "per-cli")
    assert state.get_config("heat_mode", "universal") == "per-cli"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd ~/ember-memory && python -m pytest tests/test_engine_state.py -v
```

- [ ] **Step 4: Implement EngineState**

```python
# ember_memory/core/engine/state.py
"""SQLite-backed engine state for concurrent multi-CLI safety.

Uses WAL mode so multiple CLI hooks can read/write simultaneously
without blocking each other. All state operations are atomic.
"""

import sqlite3
import threading
from datetime import datetime, timezone


# Minimum heat value to keep in the table (below this, remove)
HEAT_FLOOR = 0.01
# Minimum connection strength to keep
CONNECTION_FLOOR = 0.01


class EngineState:
    """Persistent engine state via SQLite."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._local = threading.local()
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_tables(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS heat_map (
                memory_id TEXT PRIMARY KEY,
                heat REAL NOT NULL DEFAULT 0.0,
                ai_id TEXT DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS connections (
                id_a TEXT NOT NULL,
                id_b TEXT NOT NULL,
                strength REAL NOT NULL DEFAULT 0.0,
                first_seen TEXT,
                last_seen TEXT,
                PRIMARY KEY (id_a, id_b)
            );
            CREATE TABLE IF NOT EXISTS last_accessed (
                memory_id TEXT PRIMARY KEY,
                accessed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ticks (
                key TEXT PRIMARY KEY DEFAULT 'global',
                count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            INSERT OR IGNORE INTO ticks (key, count) VALUES ('global', 0);
        """)
        conn.commit()

    # ── Ticks ──

    def get_tick(self) -> int:
        row = self._get_conn().execute(
            "SELECT count FROM ticks WHERE key = 'global'"
        ).fetchone()
        return row["count"] if row else 0

    def increment_tick(self) -> int:
        conn = self._get_conn()
        conn.execute("UPDATE ticks SET count = count + 1 WHERE key = 'global'")
        conn.commit()
        return self.get_tick()

    # ── Heat Map ──

    def get_heat(self, memory_id: str, ai_id: str | None = None) -> float:
        if ai_id:
            row = self._get_conn().execute(
                "SELECT heat FROM heat_map WHERE memory_id = ? AND ai_id = ?",
                (memory_id, ai_id)
            ).fetchone()
        else:
            row = self._get_conn().execute(
                "SELECT heat FROM heat_map WHERE memory_id = ? AND ai_id IS NULL",
                (memory_id,)
            ).fetchone()
        return row["heat"] if row else 0.0

    def set_heat(self, memory_id: str, value: float, ai_id: str | None = None):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO heat_map (memory_id, heat, ai_id) VALUES (?, ?, ?) "
            "ON CONFLICT(memory_id) DO UPDATE SET heat = ?",
            (memory_id, value, ai_id, value)
        )
        conn.commit()

    def increment_heat(self, memory_id: str, amount: float = 1.0,
                       ai_id: str | None = None):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO heat_map (memory_id, heat, ai_id) VALUES (?, ?, ?) "
            "ON CONFLICT(memory_id) DO UPDATE SET heat = heat + ?",
            (memory_id, amount, ai_id, amount)
        )
        conn.commit()

    def decay_all_heat(self, factor: float = 0.95, ai_id: str | None = None):
        conn = self._get_conn()
        if ai_id:
            conn.execute(
                "UPDATE heat_map SET heat = heat * ? WHERE ai_id = ?",
                (factor, ai_id)
            )
        else:
            conn.execute("UPDATE heat_map SET heat = heat * ?", (factor,))
        # Clean up near-zero entries
        conn.execute("DELETE FROM heat_map WHERE heat < ?", (HEAT_FLOOR,))
        conn.commit()

    def get_all_heat(self, ai_id: str | None = None) -> dict[str, float]:
        conn = self._get_conn()
        if ai_id:
            rows = conn.execute(
                "SELECT memory_id, heat FROM heat_map WHERE ai_id = ?", (ai_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT memory_id, heat FROM heat_map").fetchall()
        return {row["memory_id"]: row["heat"] for row in rows}

    # ── Connections ──

    def _normalize_pair(self, id_a: str, id_b: str) -> tuple[str, str]:
        """Ensure consistent ordering for symmetric connections."""
        return (min(id_a, id_b), max(id_a, id_b))

    def get_connection(self, id_a: str, id_b: str) -> float:
        a, b = self._normalize_pair(id_a, id_b)
        row = self._get_conn().execute(
            "SELECT strength FROM connections WHERE id_a = ? AND id_b = ?", (a, b)
        ).fetchone()
        return row["strength"] if row else 0.0

    def increment_connection(self, id_a: str, id_b: str, amount: float = 1.0):
        a, b = self._normalize_pair(id_a, id_b)
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO connections (id_a, id_b, strength, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id_a, id_b) DO UPDATE SET strength = strength + ?, last_seen = ?",
            (a, b, amount, now, now, amount, now)
        )
        conn.commit()

    def decay_all_connections(self, factor: float = 0.97):
        conn = self._get_conn()
        conn.execute("UPDATE connections SET strength = strength * ?", (factor,))
        conn.execute("DELETE FROM connections WHERE strength < ?", (CONNECTION_FLOOR,))
        conn.commit()

    def get_connections_for(self, memory_id: str) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id_a, id_b, strength FROM connections "
            "WHERE id_a = ? OR id_b = ?",
            (memory_id, memory_id)
        ).fetchall()
        results = []
        for row in rows:
            other = row["id_b"] if row["id_a"] == memory_id else row["id_a"]
            results.append({"id": other, "strength": row["strength"]})
        return results

    # ── Last Accessed ──

    def get_last_accessed(self, memory_id: str) -> str | None:
        row = self._get_conn().execute(
            "SELECT accessed_at FROM last_accessed WHERE memory_id = ?",
            (memory_id,)
        ).fetchone()
        return row["accessed_at"] if row else None

    def update_last_accessed(self, memory_id: str):
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO last_accessed (memory_id, accessed_at) VALUES (?, ?) "
            "ON CONFLICT(memory_id) DO UPDATE SET accessed_at = ?",
            (memory_id, now, now)
        )
        conn.commit()

    # ── Config ──

    def get_config(self, key: str, default: str = "") -> str:
        row = self._get_conn().execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_config(self, key: str, value: str):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, value, value)
        )
        conn.commit()
```

- [ ] **Step 5: Run tests, verify pass**
- [ ] **Step 6: Commit**

```bash
git add ember_memory/core/engine/ tests/test_engine_state.py
git commit -m "feat: add SQLite-backed engine state for concurrent multi-CLI safety"
```

---

### Task 2: Heat Map Module

**Files:**
- Create: `ember_memory/core/engine/heat.py`
- Test: `tests/test_engine_heat.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine_heat.py
import pytest
from ember_memory.core.engine.state import EngineState
from ember_memory.core.engine.heat import HeatMap


@pytest.fixture
def heat(tmp_path):
    state = EngineState(db_path=str(tmp_path / "engine.db"))
    return HeatMap(state)


def test_record_access_adds_heat(heat):
    heat.record_access("doc1")
    assert heat.get_boost("doc1") > 0.0


def test_multiple_accesses_increase_heat(heat):
    heat.record_access("doc1")
    h1 = heat.get_boost("doc1")
    heat.record_access("doc1")
    h2 = heat.get_boost("doc1")
    assert h2 > h1


def test_tick_decays_heat(heat):
    heat.record_access("doc1")
    h1 = heat.get_boost("doc1")
    heat.tick()
    h2 = heat.get_boost("doc1")
    assert h2 < h1


def test_boost_normalized_0_to_1(heat):
    for _ in range(20):
        heat.record_access("doc1")
    boost = heat.get_boost("doc1")
    assert 0.0 <= boost <= 1.0


def test_cold_memory_zero_boost(heat):
    assert heat.get_boost("never_accessed") == 0.0


def test_heat_mode_universal_default(heat):
    assert heat.get_mode() == "universal"


def test_heat_mode_per_cli(heat):
    heat.set_mode("per-cli")
    assert heat.get_mode() == "per-cli"


def test_ignore_list(heat):
    heat.set_ignored("codex", True)
    assert heat.is_ignored("codex") is True
    assert heat.is_ignored("claude") is False
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement HeatMap**

```python
# ember_memory/core/engine/heat.py
"""Heat map — tracks which memories are hot (recently/frequently accessed).

Game AI inspiration: influence maps in RTS games track recently-important
map regions. Heat decays over time. Hot memories get retrieval boosts.
"""

from ember_memory.core.engine.state import EngineState

# Heat normalization ceiling
MAX_HEAT = 5.0
# Decay factor per tick
DECAY_FACTOR = 0.95


class HeatMap:
    """Manages heat state for memory retrieval boosting."""

    def __init__(self, state: EngineState):
        self._state = state

    def record_access(self, memory_id: str, ai_id: str | None = None):
        """Record that a memory was accessed (retrieved or referenced)."""
        mode = self.get_mode()
        if mode == "per-cli" and ai_id:
            self._state.increment_heat(memory_id, 1.0, ai_id=ai_id)
        else:
            self._state.increment_heat(memory_id, 1.0)

    def get_boost(self, memory_id: str, ai_id: str | None = None) -> float:
        """Get normalized heat boost for a memory. Returns [0, 1]."""
        mode = self.get_mode()
        if mode == "per-cli" and ai_id:
            raw = self._state.get_heat(memory_id, ai_id=ai_id)
        else:
            raw = self._state.get_heat(memory_id)
        return min(raw / MAX_HEAT, 1.0)

    def tick(self, ai_id: str | None = None):
        """Apply decay to all heat values. Called once per hook firing."""
        mode = self.get_mode()
        if mode == "per-cli" and ai_id:
            self._state.decay_all_heat(DECAY_FACTOR, ai_id=ai_id)
        else:
            self._state.decay_all_heat(DECAY_FACTOR)

    def get_mode(self) -> str:
        """Get current heat mode: 'universal' or 'per-cli'."""
        return self._state.get_config("heat_mode", "universal")

    def set_mode(self, mode: str):
        """Set heat mode."""
        self._state.set_config("heat_mode", mode)

    def is_ignored(self, ai_id: str) -> bool:
        """Check if a CLI is set to ignore heat."""
        return self._state.get_config(f"heat_ignore_{ai_id}", "false") == "true"

    def set_ignored(self, ai_id: str, ignored: bool):
        """Toggle heat ignore for a CLI."""
        self._state.set_config(f"heat_ignore_{ai_id}", "true" if ignored else "false")
```

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 3: Co-occurrence Graph Module

**Files:**
- Create: `ember_memory/core/engine/connections.py`
- Test: `tests/test_engine_connections.py`

- [ ] **Step 1: Write the failing test**

Test: record co-occurrence of two IDs, connection strengthens, tick decays, established threshold at 3.0, get bonus for connected memories, bonus is normalized [0, 1].

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement ConnectionGraph**

Record co-occurrences from retrieval results (when 2+ memories return in same query). Decay per tick at 0.97. Connections with strength >= 3.0 are "established." get_bonus() returns normalized connection strength for a memory given the current result set.

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 4: Composite Scoring Module

**Files:**
- Create: `ember_memory/core/engine/scoring.py`
- Test: `tests/test_engine_scoring.py`

- [ ] **Step 1: Write the failing test**

Test: score with only similarity (no engine data), score with heat boost, score with connection bonus, score with decay penalty, full composite, normalization bounds, configurable weights.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement CompositeScorer**

```python
# ember_memory/core/engine/scoring.py
"""Composite scoring — combines semantic similarity with engine signals.

Formula:
  score = (similarity * w_sim) + (heat * w_heat) + (connection * w_conn) + (decay * w_decay)

All factors normalized to [0, 1] before weighting.
"""

import math
from datetime import datetime, timezone
from ember_memory import config

MAX_CONNECTION = 5.0


def compute_decay(last_accessed_iso: str | None, decay_lambda: float = 0.005) -> float:
    """Compute decay factor based on hours since last access. Returns [0, 1]."""
    if not last_accessed_iso:
        return 1.0  # New memory, no decay
    last = datetime.fromisoformat(last_accessed_iso)
    now = datetime.now(timezone.utc)
    hours = max(0, (now - last).total_seconds() / 3600)
    return math.exp(-decay_lambda * hours)


def composite_score(
    similarity: float,
    heat_boost: float,
    connection_bonus: float,
    decay_factor: float,
    w_sim: float | None = None,
    w_heat: float | None = None,
    w_conn: float | None = None,
    w_decay: float | None = None,
) -> float:
    """Compute composite retrieval score from all signals.

    All inputs should be in [0, 1] range (pre-normalized).
    """
    ws = w_sim if w_sim is not None else config.WEIGHT_SIMILARITY
    wh = w_heat if w_heat is not None else config.WEIGHT_HEAT
    wc = w_conn if w_conn is not None else config.WEIGHT_CONNECTION
    wd = w_decay if w_decay is not None else config.WEIGHT_DECAY

    return (similarity * ws) + (heat_boost * wh) + (connection_bonus * wc) + (decay_factor * wd)
```

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 5: Wire Engine into search.py

**Files:**
- Modify: `ember_memory/core/search.py` — integrate Engine scoring into retrieve()
- Test: `tests/test_search_with_engine.py`

This is the integration point. After backend returns raw results, the Engine re-scores them.

- [ ] **Step 1: Write the failing test**

Test: retrieve() with engine scores higher for hot memories, retrieve() without engine falls back to similarity-only, engine records access and co-occurrence after retrieval.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Update retrieve() in search.py**

After getting raw results from backend:
1. For each result, look up heat_boost, connection_bonus, decay_factor from Engine
2. Compute composite_score
3. Update heat map (record access for retrieved memories)
4. Update co-occurrence graph (record co-retrieval pairs)
5. Update last_accessed timestamps
6. Increment tick counter
7. Re-sort by composite_score

The Engine is optional — if no EngineState is provided, composite_score = similarity (backward compatible).

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 6: Engine Stats API (for Controller)

**Files:**
- Create: `ember_memory/core/engine/stats.py`
- Test: `tests/test_engine_stats.py`

Expose engine state as structured data for the controller UI and tray.

- [ ] **Step 1: Write the failing test**

Test: get_stats() returns total memories, hot count, established connections, current heat mode, per-CLI ignore flags.

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement stats module**

Simple read-only module that queries EngineState and returns a summary dict.

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

## Plan 3 Complete — What's Ready

After Plan 3, ember-memory has:
- SQLite-backed engine state (concurrent-safe)
- Heat map with universal/per-CLI/ignore modes
- Co-occurrence graph with decay and established thresholds
- Composite scoring (similarity + heat + connections + decay)
- Engine wired into search.py retrieve()
- Stats API for controller/tray
- The headline differentiator nobody else has

**Depends on:** Plan 1 (search.py, RetrievalResult, config)
**Independent of:** Plan 2 (backends)
