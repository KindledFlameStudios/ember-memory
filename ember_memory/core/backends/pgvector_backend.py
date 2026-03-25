"""PostgreSQL + pgvector v2 storage backend for Ember Memory.

v2 backend: accepts pre-computed embedding vectors — does NOT call an
embedding function internally. Callers (EmbeddingProvider → search.py) are
responsible for producing vectors before calling insert/search.

Requires:
  - psycopg2 (``pip install psycopg2-binary``)
  - PostgreSQL with the pgvector extension installed (``CREATE EXTENSION vector``)

Each collection is stored as a separate table named after the collection.
An HNSW index using cosine distance ops is created on the embedding column
for fast approximate nearest-neighbour search.

The ``<=>`` operator is pgvector's cosine *distance* (range [0, 2] for unit
vectors, but pgvector normalises so 0 = identical, 2 = opposite). We expose
similarity as ``1 - cosine_distance`` which maps to [0, 1] where 1 is a
perfect match.

Table name safety: collection names are validated to contain only
alphanumeric characters and underscores. This is the single place where
collection names appear in SQL without parameterisation — parameterised
queries are used for all data values.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ember_memory.core.backends.base import MemoryBackend

# Allowed characters for collection names (used as SQL table names).
_SAFE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_name(name: str) -> str:
    """Raise ValueError if *name* is not a safe SQL identifier."""
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid collection name {name!r}: must start with a letter or "
            "underscore and contain only alphanumeric characters and underscores."
        )
    return name


def _vec_to_pg(embedding: list[float]) -> str:
    """Serialise a Python float list to pgvector literal format ``[a,b,c]``."""
    return "[" + ",".join(str(v) for v in embedding) + "]"


class PgvectorBackend(MemoryBackend):
    """PostgreSQL + pgvector storage backend (v2 vector-native interface).

    Constructor parameters
    ----------------------
    dsn : str
        Full libpq connection string, e.g.
        ``"host=localhost dbname=ember_memory user=postgres"``.
        When non-empty, the individual keyword arguments are ignored.
    host : str
        Database host (default ``"localhost"``).
    port : int
        Database port (default ``5432``).
    dbname : str
        Database name (default ``"ember_memory"``).
    user : str
        Database user (default ``""``).
    password : str
        Database password (default ``""``).
    """

    def __init__(
        self,
        dsn: str = "",
        host: str = "localhost",
        port: int = 5432,
        dbname: str = "ember_memory",
        user: str = "",
        password: str = "",
    ) -> None:
        self._dsn = dsn
        self._host = host
        self._port = port
        self._dbname = dbname
        self._user = user
        self._password = password
        self._conn: Any = None  # psycopg2 connection

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _require_conn(self) -> Any:
        if self._conn is None:
            raise RuntimeError(
                "PgvectorBackend.connect() must be called before using the backend."
            )
        return self._conn

    def _cursor(self) -> Any:
        return self._require_conn().cursor()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Open a psycopg2 connection and ensure the vector extension exists.

        Raises
        ------
        RuntimeError
            If psycopg2 is not installed or the connection cannot be established.
        """
        try:
            import psycopg2
        except ImportError as exc:
            raise RuntimeError(
                "psycopg2 is required for PgvectorBackend. "
                "Install it with: pip install psycopg2-binary"
            ) from exc

        if self._dsn:
            self._conn = psycopg2.connect(self._dsn)
        else:
            kwargs: dict[str, Any] = {
                "host": self._host,
                "port": self._port,
                "dbname": self._dbname,
            }
            if self._user:
                kwargs["user"] = self._user
            if self._password:
                kwargs["password"] = self._password
            self._conn = psycopg2.connect(**kwargs)

        with self._cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        self._conn.commit()

    # ── Collection management ─────────────────────────────────────────────────

    def create_collection(
        self,
        name: str,
        dimension: int,
        description: str | None = None,
    ) -> None:
        """Create a table for *name* if it does not already exist.

        Columns: id VARCHAR PRIMARY KEY, content TEXT, metadata JSONB,
        embedding vector({dimension}).

        An HNSW index using cosine distance ops is created on the embedding
        column for efficient approximate nearest-neighbour search.
        """
        _validate_name(name)
        conn = self._require_conn()
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {name} (
                    id        VARCHAR PRIMARY KEY,
                    content   TEXT        NOT NULL,
                    metadata  JSONB       NOT NULL DEFAULT '{{}}',
                    embedding vector({dimension}) NOT NULL
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {name}_embedding_hnsw_idx
                ON {name}
                USING hnsw (embedding vector_cosine_ops)
                """
            )
        conn.commit()

    def delete_collection(self, name: str) -> int:
        """Drop the table for *name*. Returns the row count before deletion, or 0."""
        _validate_name(name)
        conn = self._require_conn()
        count = self._table_count(name)
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {name}")
        conn.commit()
        return count

    def list_collections(self) -> list[dict]:
        """Return a list of dicts with ``name`` and ``count`` for each collection.

        Only tables that were created through this backend (i.e. those that
        have the expected column layout) are returned. We detect them by
        querying ``information_schema.columns`` for tables that have an
        ``embedding`` column in the current schema.
        """
        conn = self._require_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT table_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND column_name = 'embedding'
                ORDER BY table_name
                """
            )
            rows = cur.fetchall()

        out: list[dict] = []
        for (table_name,) in rows:
            try:
                count = self._table_count(table_name)
            except Exception:
                count = 0
            out.append({"name": table_name, "count": count})
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
        """Insert a single document. Returns the new total count."""
        _validate_name(collection)
        conn = self._require_conn()
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {collection} (id, content, metadata, embedding)
                VALUES (%s, %s, %s, %s::vector)
                """,
                (doc_id, content, json.dumps(metadata), _vec_to_pg(embedding)),
            )
        conn.commit()
        return self._table_count(collection)

    def insert_batch(
        self,
        collection: str,
        ids: list[str],
        contents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> int:
        """Insert multiple documents. Returns the number of documents inserted."""
        if not ids:
            return 0
        _validate_name(collection)
        conn = self._require_conn()
        rows = [
            (doc_id, content, json.dumps(meta), _vec_to_pg(emb))
            for doc_id, content, emb, meta in zip(ids, contents, embeddings, metadatas)
        ]
        with conn.cursor() as cur:
            cur.executemany(
                f"""
                INSERT INTO {collection} (id, content, metadata, embedding)
                VALUES (%s, %s, %s, %s::vector)
                """,
                rows,
            )
        conn.commit()
        return len(ids)

    def update(
        self,
        collection: str,
        doc_id: str,
        content: str,
        embedding: list[float],
        metadata: dict,
    ) -> bool:
        """Replace content, embedding, and metadata for an existing document.

        Returns True if the document was found and updated, False otherwise.
        """
        _validate_name(collection)
        conn = self._require_conn()
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {collection}
                SET content   = %s,
                    metadata  = %s,
                    embedding = %s::vector
                WHERE id = %s
                """,
                (content, json.dumps(metadata), _vec_to_pg(embedding), doc_id),
            )
            updated = cur.rowcount
        conn.commit()
        return updated > 0

    def delete(self, collection: str, doc_id: str) -> bool:
        """Remove a single document. Returns True if it existed, False otherwise."""
        _validate_name(collection)
        conn = self._require_conn()
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {collection} WHERE id = %s",
                (doc_id,),
            )
            deleted = cur.rowcount
        conn.commit()
        return deleted > 0

    # ── Query ─────────────────────────────────────────────────────────────────

    def search(
        self,
        collection: str,
        query_embedding: list[float],
        limit: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """Nearest-neighbour search using cosine distance (``<=>`` operator).

        Similarity is returned as ``1 - cosine_distance`` so that:
        - 1.0 = identical vectors
        - 0.5 = orthogonal vectors
        - 0.0 = opposite vectors

        Args:
            collection:      Target collection table.
            query_embedding: Pre-computed query vector.
            limit:           Maximum results to return.
            filters:         Optional metadata equality filters. Each
                             ``{field: value}`` pair becomes a JSONB containment
                             check (``metadata @> %s``).

        Returns:
            List of dicts ordered by descending similarity, each with:
            ``id``, ``content``, ``metadata``, ``similarity``.
        """
        _validate_name(collection)
        conn = self._require_conn()

        vec_str = _vec_to_pg(query_embedding)
        params: list[Any] = [vec_str, vec_str]
        where_clause = ""

        if filters:
            conditions = []
            for field, value in filters.items():
                conditions.append("metadata @> %s")
                params.append(json.dumps({field: value}))
            where_clause = "WHERE " + " AND ".join(conditions)

        params.append(limit)

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, content, metadata,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM {collection}
                {where_clause}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()

        out: list[dict] = []
        for row_id, content, metadata, similarity in rows:
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            out.append({
                "id": row_id,
                "content": content,
                "metadata": metadata,
                "similarity": float(similarity),
            })
        return out

    def get(self, collection: str, doc_id: str) -> dict | None:
        """Retrieve a single document by ID. Returns None if not found."""
        _validate_name(collection)
        conn = self._require_conn()
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, content, metadata FROM {collection} WHERE id = %s",
                (doc_id,),
            )
            row = cur.fetchone()

        if row is None:
            return None
        row_id, content, metadata = row
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return {"id": row_id, "content": content, "metadata": metadata}

    # ── Inspection ────────────────────────────────────────────────────────────

    def collection_count(self, collection: str) -> int:
        """Return the document count for *collection*, or 0 if it does not exist."""
        _validate_name(collection)
        return self._table_count(collection)

    def collection_peek(self, collection: str, limit: int = 5) -> list[dict]:
        """Return up to *limit* documents from *collection* without searching."""
        _validate_name(collection)
        conn = self._require_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT id, content, metadata FROM {collection} LIMIT %s",
                    (limit,),
                )
                rows = cur.fetchall()
        except Exception:
            conn.rollback()
            return []

        out: list[dict] = []
        for row_id, content, metadata in rows:
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            out.append({"id": row_id, "content": content, "metadata": metadata})
        return out

    # ── Private utilities ─────────────────────────────────────────────────────

    def _table_count(self, table: str) -> int:
        """Return COUNT(*) for *table*, or 0 on any error (e.g. table missing)."""
        _validate_name(table)
        conn = self._require_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                result = cur.fetchone()
            return int(result[0]) if result else 0
        except Exception:
            conn.rollback()
            return 0
