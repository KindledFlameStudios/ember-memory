"""SQLite-vec v2 storage backend for Ember Memory.

Ultra-minimal vector search backend using the sqlite-vec extension.
Zero external server dependencies — pure SQLite with vec0 virtual tables.

Architecture
------------
One SQLite database file per backend instance. Inside that file:

- ``_collections``        — metadata table tracking collection names,
                           dimensions, and optional descriptions.
- ``{name}_docs``         — document store: id (TEXT PK), content, metadata
                           (JSON), plus a ``rowid_`` integer that mirrors the
                           SQLite implicit rowid so we can join to the vec table.
- ``{name}_vec``          — vec0 virtual table keyed on SQLite rowid; stores
                           the float embeddings for KNN search.

The vec0 virtual table only supports integer rowids, so ``_docs`` keeps a
``rowid_`` column that tracks the assigned rowid for each inserted document.
This lets us JOIN from a KNN result (rowid) back to the document record.

Similarity normalisation
------------------------
sqlite-vec's KNN query returns cosine *distance* in [0, 2].  We convert to
similarity in [0, 1] via ``max(0.0, 1.0 - distance)``, matching the ChromaDB
backend convention so callers get consistent values regardless of backend.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from typing import Any

from ember_memory.core.backends.base import MemoryBackend


def _try_load_sqlite_vec(conn: sqlite3.Connection) -> None:
    """Load the sqlite-vec extension into *conn*.

    Raises:
        RuntimeError: if sqlite-vec cannot be imported or loaded.
    """
    try:
        import sqlite_vec  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "sqlite-vec is not installed. Run: pip install sqlite-vec"
        ) from exc

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def _pack_floats(values: list[float]) -> bytes:
    """Encode a list of floats as little-endian IEEE-754 binary (vec0 format)."""
    return struct.pack(f"{len(values)}f", *values)


class SqliteVecBackend(MemoryBackend):
    """SQLite + sqlite-vec v2 storage backend.

    Args:
        db_path: Filesystem path to the SQLite database file, e.g.
                 ``"/tmp/my_memory.db"``.  Use ``":memory:"`` for an
                 in-process ephemeral database (useful in tests).
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Open the SQLite database, load sqlite-vec, and create bootstrap tables."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        _try_load_sqlite_vec(conn)

        # Enable WAL for better concurrent read performance
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        # Collections registry
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _collections (
                name        TEXT PRIMARY KEY,
                dimension   INTEGER NOT NULL,
                description TEXT
            )
            """
        )
        conn.commit()
        self._conn = conn

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError(
                "SqliteVecBackend.connect() must be called before using the backend."
            )
        return self._conn

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _docs_table(self, collection: str) -> str:
        return f"{collection}_docs"

    def _vec_table(self, collection: str) -> str:
        return f"{collection}_vec"

    def _collection_exists(self, conn: sqlite3.Connection, name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM _collections WHERE name = ?", (name,)
        ).fetchone()
        return row is not None

    def _require_collection(self, conn: sqlite3.Connection, name: str) -> None:
        if not self._collection_exists(conn, name):
            raise ValueError(f"Collection '{name}' does not exist.")

    def _get_dimension(self, conn: sqlite3.Connection, name: str) -> int:
        row = conn.execute(
            "SELECT dimension FROM _collections WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Collection '{name}' not found in registry.")
        return row[0]

    # ── Collection management ─────────────────────────────────────────────────

    def create_collection(
        self,
        name: str,
        dimension: int,
        description: str | None = None,
    ) -> None:
        """Create the docs + vec tables for *name*.  Idempotent — safe to call twice."""
        conn = self._require_conn()

        if self._collection_exists(conn, name):
            return  # already exists, nothing to do

        docs_t = self._docs_table(name)
        vec_t = self._vec_table(name)

        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{docs_t}" (
                id       TEXT PRIMARY KEY,
                content  TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{{}}',
                rowid_   INTEGER
            )
            """
        )
        conn.execute(
            f'CREATE VIRTUAL TABLE IF NOT EXISTS "{vec_t}" '
            f"USING vec0(embedding float[{dimension}])"
        )
        conn.execute(
            "INSERT OR IGNORE INTO _collections(name, dimension, description) "
            "VALUES (?, ?, ?)",
            (name, dimension, description),
        )
        conn.commit()

    def delete_collection(self, name: str) -> int:
        """Drop the collection tables. Returns doc count before deletion, or 0."""
        conn = self._require_conn()

        if not self._collection_exists(conn, name):
            return 0

        docs_t = self._docs_table(name)
        vec_t = self._vec_table(name)

        count_row = conn.execute(f'SELECT COUNT(*) FROM "{docs_t}"').fetchone()
        count: int = count_row[0] if count_row else 0

        conn.execute(f'DROP TABLE IF EXISTS "{vec_t}"')
        conn.execute(f'DROP TABLE IF EXISTS "{docs_t}"')
        conn.execute("DELETE FROM _collections WHERE name = ?", (name,))
        conn.commit()
        return count

    def list_collections(self) -> list[dict]:
        """Return a list of dicts with 'name', 'count', 'dimension', 'description'."""
        conn = self._require_conn()
        rows = conn.execute(
            "SELECT name, dimension, description FROM _collections ORDER BY name"
        ).fetchall()

        out: list[dict] = []
        for row in rows:
            col_name: str = row[0]
            docs_t = self._docs_table(col_name)
            try:
                count_row = conn.execute(
                    f'SELECT COUNT(*) FROM "{docs_t}"'
                ).fetchone()
                count = count_row[0] if count_row else 0
            except Exception:
                count = 0

            entry: dict[str, Any] = {
                "name": col_name,
                "count": count,
                "dimension": row[1],
            }
            if row[2] is not None:
                entry["description"] = row[2]
            out.append(entry)
        return out

    # ── Document mutation ─────────────────────────────────────────────────────

    def insert(
        self,
        collection: str,
        doc_id: str,
        content: str,
        embedding: list[float],
        metadata: dict,
    ) -> int:
        """Insert a single document with its pre-computed embedding.

        Returns the new total document count for the collection.
        """
        conn = self._require_conn()
        self._require_collection(conn, collection)

        docs_t = self._docs_table(collection)
        vec_t = self._vec_table(collection)

        meta_json = json.dumps(metadata)
        cur = conn.execute(
            f'INSERT INTO "{docs_t}"(id, content, metadata) VALUES (?, ?, ?)',
            (doc_id, content, meta_json),
        )
        rowid = cur.lastrowid

        conn.execute(
            f'INSERT INTO "{vec_t}"(rowid, embedding) VALUES (?, ?)',
            (rowid, _pack_floats(embedding)),
        )
        # Keep rowid_ in sync so JOIN works
        conn.execute(
            f'UPDATE "{docs_t}" SET rowid_ = ? WHERE id = ?',
            (rowid, doc_id),
        )
        conn.commit()

        count_row = conn.execute(
            f'SELECT COUNT(*) FROM "{docs_t}"'
        ).fetchone()
        return count_row[0] if count_row else 0

    def insert_batch(
        self,
        collection: str,
        ids: list[str],
        contents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> int:
        """Insert multiple documents in a single transaction.

        Returns the number of documents successfully inserted.
        """
        if not ids:
            return 0

        conn = self._require_conn()
        self._require_collection(conn, collection)

        docs_t = self._docs_table(collection)
        vec_t = self._vec_table(collection)

        inserted = 0
        for doc_id, content, embedding, metadata in zip(ids, contents, embeddings, metadatas):
            meta_json = json.dumps(metadata)
            cur = conn.execute(
                f'INSERT INTO "{docs_t}"(id, content, metadata) VALUES (?, ?, ?)',
                (doc_id, content, meta_json),
            )
            rowid = cur.lastrowid
            conn.execute(
                f'INSERT INTO "{vec_t}"(rowid, embedding) VALUES (?, ?)',
                (rowid, _pack_floats(embedding)),
            )
            conn.execute(
                f'UPDATE "{docs_t}" SET rowid_ = ? WHERE id = ?',
                (rowid, doc_id),
            )
            inserted += 1

        conn.commit()
        return inserted

    def update(
        self,
        collection: str,
        doc_id: str,
        content: str,
        embedding: list[float],
        metadata: dict,
    ) -> bool:
        """Replace a document's content, embedding, and metadata.

        Returns True if the document existed and was updated, False otherwise.
        """
        conn = self._require_conn()
        self._require_collection(conn, collection)

        docs_t = self._docs_table(collection)
        vec_t = self._vec_table(collection)

        existing = conn.execute(
            f'SELECT rowid_ FROM "{docs_t}" WHERE id = ?', (doc_id,)
        ).fetchone()
        if existing is None:
            return False

        old_rowid: int = existing[0]
        meta_json = json.dumps(metadata)

        # Update the doc record
        conn.execute(
            f'UPDATE "{docs_t}" SET content = ?, metadata = ? WHERE id = ?',
            (content, meta_json, doc_id),
        )
        # Replace the vector: delete old rowid, insert new one
        # (The doc rowid doesn't change on UPDATE, so we can reuse it.)
        conn.execute(
            f'DELETE FROM "{vec_t}" WHERE rowid = ?', (old_rowid,)
        )
        conn.execute(
            f'INSERT INTO "{vec_t}"(rowid, embedding) VALUES (?, ?)',
            (old_rowid, _pack_floats(embedding)),
        )
        conn.commit()
        return True

    def delete(self, collection: str, doc_id: str) -> bool:
        """Remove a document from the collection.

        Returns True if it existed, False if not found.
        """
        conn = self._require_conn()
        self._require_collection(conn, collection)

        docs_t = self._docs_table(collection)
        vec_t = self._vec_table(collection)

        existing = conn.execute(
            f'SELECT rowid_ FROM "{docs_t}" WHERE id = ?', (doc_id,)
        ).fetchone()
        if existing is None:
            return False

        rowid: int = existing[0]
        conn.execute(f'DELETE FROM "{vec_t}" WHERE rowid = ?', (rowid,))
        conn.execute(f'DELETE FROM "{docs_t}" WHERE id = ?', (doc_id,))
        conn.commit()
        return True

    # ── Query ─────────────────────────────────────────────────────────────────

    def search(
        self,
        collection: str,
        query_embedding: list[float],
        limit: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """KNN search using the pre-computed query vector.

        sqlite-vec returns cosine distance in [0, 2].  We normalise to
        similarity = max(0, 1 - distance) so values are in [0, 1] and
        1.0 means identical.

        The optional *filters* dict is evaluated as equality conditions on
        the JSON metadata stored in the docs table.  Each key/value pair
        is matched via SQLite's ``json_extract(metadata, '$.key') = value``.
        All conditions are AND-ed together.

        Returns:
            List of dicts ordered by descending similarity, each with:
            ``id``, ``content``, ``metadata`` (dict), ``similarity`` (float).
        """
        conn = self._require_conn()
        self._require_collection(conn, collection)

        docs_t = self._docs_table(collection)
        vec_t = self._vec_table(collection)

        count_row = conn.execute(
            f'SELECT COUNT(*) FROM "{docs_t}"'
        ).fetchone()
        if not count_row or count_row[0] == 0:
            return []

        k = min(limit, count_row[0])
        packed_query = _pack_floats(query_embedding)

        # Build the WHERE clause for metadata filters
        filter_clauses: list[str] = []
        filter_params: list[Any] = []
        if filters:
            for field, value in filters.items():
                filter_clauses.append(
                    f"json_extract(d.metadata, '$.{field}') = ?"
                )
                filter_params.append(value)

        filter_sql = ""
        if filter_clauses:
            filter_sql = " AND " + " AND ".join(filter_clauses)

        sql = f"""
            SELECT d.id, d.content, d.metadata, v.distance
            FROM "{vec_t}" v
            JOIN "{docs_t}" d ON d.rowid_ = v.rowid
            WHERE v.embedding MATCH ?
              AND v.k = ?
              {filter_sql}
            ORDER BY v.distance
        """
        params: list[Any] = [packed_query, k] + filter_params
        rows = conn.execute(sql, params).fetchall()

        out: list[dict] = []
        for row in rows:
            distance: float = row[3] if row[3] is not None else 2.0
            similarity = max(0.0, 1.0 - distance)
            try:
                meta = json.loads(row[2]) if row[2] else {}
            except (json.JSONDecodeError, TypeError):
                meta = {}
            out.append(
                {
                    "id": row[0],
                    "content": row[1],
                    "metadata": meta,
                    "similarity": similarity,
                }
            )
        return out

    def get(self, collection: str, doc_id: str) -> dict | None:
        """Retrieve a single document by ID, or None if not found."""
        conn = self._require_conn()
        self._require_collection(conn, collection)

        docs_t = self._docs_table(collection)
        row = conn.execute(
            f'SELECT id, content, metadata FROM "{docs_t}" WHERE id = ?',
            (doc_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            meta = json.loads(row[2]) if row[2] else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}
        return {"id": row[0], "content": row[1], "metadata": meta}

    # ── Inspection ────────────────────────────────────────────────────────────

    def collection_count(self, collection: str) -> int:
        """Return the document count for *collection*, or 0 if it does not exist."""
        conn = self._require_conn()
        if not self._collection_exists(conn, collection):
            return 0
        docs_t = self._docs_table(collection)
        try:
            row = conn.execute(
                f'SELECT COUNT(*) FROM "{docs_t}"'
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def collection_peek(self, collection: str, limit: int = 5) -> list[dict]:
        """Return up to *limit* documents from the collection without searching."""
        conn = self._require_conn()
        if not self._collection_exists(conn, collection):
            return []

        docs_t = self._docs_table(collection)
        try:
            rows = conn.execute(
                f'SELECT id, content, metadata FROM "{docs_t}" LIMIT ?',
                (limit,),
            ).fetchall()
        except Exception:
            return []

        out: list[dict] = []
        for row in rows:
            try:
                meta = json.loads(row[2]) if row[2] else {}
            except (json.JSONDecodeError, TypeError):
                meta = {}
            out.append({"id": row[0], "content": row[1], "metadata": meta})
        return out
