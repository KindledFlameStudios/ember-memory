"""
SQLite-backed state store for the Ember Engine.

Stores heat map, co-occurrence connections, access timestamps, tick counter,
and config. WAL mode + busy_timeout for concurrent multi-CLI safety.

Physical location: <db_path> (typically ~/.ember-memory/engine/engine.db)
"""

import sqlite3
import threading
from datetime import datetime, timezone


def _now_iso() -> str:
    """Current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _normalize_pair(id_a: str, id_b: str) -> tuple[str, str]:
    """Ensure A < B so (A,B) and (B,A) map to the same row."""
    return (id_a, id_b) if id_a <= id_b else (id_b, id_a)


_GLOBAL_AI_SENTINEL = ""  # stored when ai_id=None so PRIMARY KEY works


def _ai_key(ai_id: str | None) -> str:
    """Convert public ai_id (None = global scope) to stored key."""
    return ai_id if ai_id is not None else _GLOBAL_AI_SENTINEL


class EngineState:
    """
    Persistent state store for the Ember Engine.

    Thread-safe via threading.local() connection pool.
    SQLite WAL mode allows concurrent readers + one writer without contention.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._local = threading.local()
        # Initialise schema using one connection (closes after setup)
        conn = self._connect()
        self._create_tables(conn)

    # ── Connection management ────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        """Return the per-thread connection, creating it if needed."""
        if not getattr(self._local, "conn", None):
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=5.0,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    @property
    def _conn(self) -> sqlite3.Connection:
        return self._connect()

    # ── Schema ───────────────────────────────────────────────────────────────

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS heat_map (
                memory_id  TEXT    NOT NULL,
                heat       REAL    NOT NULL DEFAULT 0.0,
                ai_id      TEXT    NOT NULL DEFAULT '',
                PRIMARY KEY (memory_id, ai_id)
            );
            -- ai_id = '' means global scope (ai_id=None in the Python API).

            CREATE TABLE IF NOT EXISTS connections (
                id_a        TEXT NOT NULL,
                id_b        TEXT NOT NULL,
                strength    REAL NOT NULL DEFAULT 0.0,
                first_seen  TEXT NOT NULL,
                last_seen   TEXT NOT NULL,
                PRIMARY KEY (id_a, id_b)
            );

            CREATE TABLE IF NOT EXISTS last_accessed (
                memory_id   TEXT PRIMARY KEY,
                accessed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ticks (
                key    TEXT PRIMARY KEY,
                count  INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS memory_meta (
                memory_id   TEXT PRIMARY KEY,
                collection  TEXT NOT NULL DEFAULT '',
                preview     TEXT NOT NULL DEFAULT ''
            );
            """
        )
        conn.commit()

    # ── Ticks ────────────────────────────────────────────────────────────────

    def get_tick(self) -> int:
        """Return the current global tick count (0 if never set)."""
        row = self._conn.execute(
            "SELECT count FROM ticks WHERE key = 'global'"
        ).fetchone()
        return int(row["count"]) if row else 0

    def increment_tick(self) -> int:
        """Increment the global tick and return the new value."""
        self._conn.execute(
            """
            INSERT INTO ticks (key, count) VALUES ('global', 1)
            ON CONFLICT(key) DO UPDATE SET count = count + 1
            """
        )
        self._conn.commit()
        return self.get_tick()

    # ── Heat Map ─────────────────────────────────────────────────────────────

    def get_heat(self, memory_id: str, ai_id: str | None = None) -> float:
        """Return heat for a memory (0.0 if not found)."""
        row = self._conn.execute(
            "SELECT heat FROM heat_map WHERE memory_id = ? AND ai_id = ?",
            (memory_id, _ai_key(ai_id)),
        ).fetchone()
        return float(row["heat"]) if row else 0.0

    def set_heat(self, memory_id: str, value: float, ai_id: str | None = None) -> None:
        """Set heat for a memory to an exact value."""
        self._conn.execute(
            """
            INSERT INTO heat_map (memory_id, heat, ai_id) VALUES (?, ?, ?)
            ON CONFLICT(memory_id, ai_id) DO UPDATE SET heat = excluded.heat
            """,
            (memory_id, value, _ai_key(ai_id)),
        )
        self._conn.commit()

    def increment_heat(
        self, memory_id: str, amount: float = 1.0, ai_id: str | None = None
    ) -> None:
        """Add amount to heat for a memory (inserts with amount if new)."""
        self._conn.execute(
            """
            INSERT INTO heat_map (memory_id, heat, ai_id) VALUES (?, ?, ?)
            ON CONFLICT(memory_id, ai_id) DO UPDATE SET heat = heat + excluded.heat
            """,
            (memory_id, amount, _ai_key(ai_id)),
        )
        self._conn.commit()

    def decay_all_heat(self, factor: float = 0.95, ai_id: str | None = None) -> None:
        """
        Multiply all heat values by factor for the given ai_id scope.
        Entries that fall below 0.01 are removed.
        """
        key = _ai_key(ai_id)
        self._conn.execute(
            "UPDATE heat_map SET heat = heat * ? WHERE ai_id = ?",
            (factor, key),
        )
        self._conn.execute(
            "DELETE FROM heat_map WHERE heat < 0.01 AND ai_id = ?",
            (key,),
        )
        self._conn.commit()

    def get_all_heat(self, ai_id: str | None = None) -> dict[str, float]:
        """Return {memory_id: heat} for all entries in the given ai_id scope."""
        rows = self._conn.execute(
            "SELECT memory_id, heat FROM heat_map WHERE ai_id = ?",
            (_ai_key(ai_id),),
        ).fetchall()
        return {row["memory_id"]: float(row["heat"]) for row in rows}

    # ── Memory Metadata ────────────────────────────────────────────────────

    def upsert_memory_meta(self, memory_id: str, collection: str, preview: str) -> None:
        """Store or update metadata for a memory (collection + content preview)."""
        self._conn.execute(
            """
            INSERT INTO memory_meta (memory_id, collection, preview)
            VALUES (?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                collection = excluded.collection,
                preview = excluded.preview
            """,
            (memory_id, collection, preview[:500]),
        )
        self._conn.commit()

    def get_memory_meta(self, memory_id: str) -> dict | None:
        """Return {collection, preview} for a memory, or None."""
        row = self._conn.execute(
            "SELECT collection, preview FROM memory_meta WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        if row:
            return {"collection": row["collection"], "preview": row["preview"]}
        return None

    def get_all_memory_meta(self) -> dict[str, dict]:
        """Return {memory_id: {collection, preview}} for all tracked memories."""
        rows = self._conn.execute(
            "SELECT memory_id, collection, preview FROM memory_meta"
        ).fetchall()
        return {
            row["memory_id"]: {"collection": row["collection"], "preview": row["preview"]}
            for row in rows
        }

    # ── Connections ──────────────────────────────────────────────────────────

    def get_connection(self, id_a: str, id_b: str) -> float:
        """Return connection strength between two memories (0.0 if not found)."""
        a, b = _normalize_pair(id_a, id_b)
        row = self._conn.execute(
            "SELECT strength FROM connections WHERE id_a = ? AND id_b = ?",
            (a, b),
        ).fetchone()
        return float(row["strength"]) if row else 0.0

    def increment_connection(
        self, id_a: str, id_b: str, amount: float = 1.0
    ) -> None:
        """
        Add amount to the connection strength between two memories.
        Sets first_seen on insert and always updates last_seen.
        """
        a, b = _normalize_pair(id_a, id_b)
        now = _now_iso()
        self._conn.execute(
            """
            INSERT INTO connections (id_a, id_b, strength, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id_a, id_b) DO UPDATE SET
                strength  = strength + excluded.strength,
                last_seen = excluded.last_seen
            """,
            (a, b, amount, now, now),
        )
        self._conn.commit()

    def decay_all_connections(self, factor: float = 0.97) -> None:
        """
        Multiply all connection strengths by factor.
        Entries below 0.01 are removed.
        """
        self._conn.execute("UPDATE connections SET strength = strength * ?", (factor,))
        self._conn.execute("DELETE FROM connections WHERE strength < 0.01")
        self._conn.commit()

    def get_connections_for(self, memory_id: str) -> list[dict]:
        """
        Return all connections involving memory_id as a list of
        [{"id": <other_memory_id>, "strength": <float>}, ...].
        """
        rows = self._conn.execute(
            """
            SELECT
                CASE WHEN id_a = ? THEN id_b ELSE id_a END AS other_id,
                strength
            FROM connections
            WHERE id_a = ? OR id_b = ?
            ORDER BY strength DESC
            """,
            (memory_id, memory_id, memory_id),
        ).fetchall()
        return [{"id": row["other_id"], "strength": float(row["strength"])} for row in rows]

    # ── Last Accessed ────────────────────────────────────────────────────────

    def get_last_accessed(self, memory_id: str) -> str | None:
        """Return ISO timestamp of last access, or None if never accessed."""
        row = self._conn.execute(
            "SELECT accessed_at FROM last_accessed WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        return row["accessed_at"] if row else None

    def update_last_accessed(self, memory_id: str) -> None:
        """Record now (UTC ISO) as the last access time for a memory."""
        self._conn.execute(
            """
            INSERT INTO last_accessed (memory_id, accessed_at) VALUES (?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET accessed_at = excluded.accessed_at
            """,
            (memory_id, _now_iso()),
        )
        self._conn.commit()

    # ── Config ───────────────────────────────────────────────────────────────

    def get_config(self, key: str, default: str = "") -> str:
        """Return a config value by key, or default if not set."""
        row = self._conn.execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_config(self, key: str, value: str) -> None:
        """Persist a config key-value pair."""
        self._conn.execute(
            """
            INSERT INTO config (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self._conn.commit()

    def get_workspace_config(self):
        """Get full workspace configuration as dict."""
        raw = self.get_config("workspaces", "{}")
        import json
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def save_workspace_config(self, config):
        """Save workspace configuration."""
        import json
        self.set_config("workspaces", json.dumps(config))
