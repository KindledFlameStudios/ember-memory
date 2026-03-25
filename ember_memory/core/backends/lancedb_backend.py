"""LanceDB v2 storage backend for Ember Memory.

v2 backend: accepts pre-computed embedding vectors — does NOT call an
embedding function internally. Callers (EmbeddingProvider → search.py) are
responsible for producing vectors before calling insert/search.

LanceDB uses tables instead of collections; this backend maps collection
names 1-to-1 with table names.

Metadata is stored as a JSON string column because LanceDB works best with
flat, fixed schemas — arbitrary metadata dicts cannot map cleanly to columns.

Distance metric is cosine. Similarity is normalised from cosine distance
[0, 1] to similarity [0, 1] via ``1 - distance``.
"""

from __future__ import annotations

import json

import lancedb
import pyarrow as pa

from ember_memory.core.backends.base import MemoryBackend


class LanceBackend(MemoryBackend):
    """LanceDB persistent storage backend (v2 vector-native interface).

    Each call to :meth:`create_collection` creates a LanceDB table.
    The table schema is fixed:

    * ``id``       — string primary key
    * ``content``  — raw document text
    * ``vector``   — fixed-size float32 list matching *dimension*
    * ``metadata`` — JSON-encoded string (decoded back to dict on read)
    """

    def __init__(self, data_dir: str) -> None:
        self._data_dir = data_dir
        self._db: lancedb.DBConnection | None = None
        # Cache dimension per table so we can rebuild the schema for re-opens.
        self._dims: dict[str, int] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Open the local LanceDB database. Must be called once after construction."""
        self._db = lancedb.connect(self._data_dir)

    def _require_db(self) -> lancedb.DBConnection:
        if self._db is None:
            raise RuntimeError(
                "LanceBackend.connect() must be called before using the backend."
            )
        return self._db

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _build_schema(dimension: int) -> pa.Schema:
        return pa.schema([
            pa.field("id", pa.string()),
            pa.field("content", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dimension)),
            pa.field("metadata", pa.string()),
        ])

    def _get_table(self, name: str):
        """Open an existing table by name. Raises if it does not exist."""
        db = self._require_db()
        if name not in db.table_names():
            raise KeyError(f"Collection '{name}' does not exist.")
        return db.open_table(name)

    @staticmethod
    def _row_to_doc(row: dict) -> dict:
        """Convert a raw LanceDB row dict to the standard ``{id, content, metadata}`` shape."""
        raw_meta = row.get("metadata", "{}")
        try:
            meta = json.loads(raw_meta) if raw_meta else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}
        return {
            "id": row["id"],
            "content": row.get("content", ""),
            "metadata": meta,
        }

    # ── Collection management ─────────────────────────────────────────────────

    def create_collection(
        self,
        name: str,
        dimension: int,
        description: str | None = None,
    ) -> None:
        """Create a LanceDB table for this collection. No-op if it already exists."""
        db = self._require_db()
        schema = self._build_schema(dimension)
        db.create_table(name, schema=schema, exist_ok=True)
        self._dims[name] = dimension

    def delete_collection(self, name: str) -> int:
        """Drop a table. Returns the document count before deletion, or 0."""
        db = self._require_db()
        if name not in db.table_names():
            return 0
        tbl = db.open_table(name)
        count = tbl.count_rows()
        db.drop_table(name)
        self._dims.pop(name, None)
        return count

    def list_collections(self) -> list[dict]:
        """Return list of dicts with ``name`` and ``count`` for each table."""
        db = self._require_db()
        out: list[dict] = []
        for name in db.table_names():
            try:
                tbl = db.open_table(name)
                count = tbl.count_rows()
            except Exception:
                count = 0
            entry: dict = {"name": name, "count": count}
            if name in self._dims:
                entry["dimension"] = self._dims[name]
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
        """Insert a single document with a pre-computed embedding vector.

        Returns the collection's new total document count.
        """
        tbl = self._get_table(collection)
        tbl.add([{
            "id": doc_id,
            "content": content,
            "vector": [float(v) for v in embedding],
            "metadata": json.dumps(metadata),
        }])
        return tbl.count_rows()

    def insert_batch(
        self,
        collection: str,
        ids: list[str],
        contents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> int:
        """Insert multiple documents in a single LanceDB add call.

        Returns the number of documents inserted (0 for an empty batch).
        """
        if not ids:
            return 0
        tbl = self._get_table(collection)
        rows = [
            {
                "id": ids[i],
                "content": contents[i],
                "vector": [float(v) for v in embeddings[i]],
                "metadata": json.dumps(metadatas[i]),
            }
            for i in range(len(ids))
        ]
        tbl.add(rows)
        return len(ids)

    def update(
        self,
        collection: str,
        doc_id: str,
        content: str,
        embedding: list[float],
        metadata: dict,
    ) -> bool:
        """Replace a document's content, vector, and metadata.

        LanceDB does not support native update-by-id, so this is implemented
        as delete-then-insert. Returns True if the document existed, False otherwise.
        """
        tbl = self._get_table(collection)
        # Check existence before deleting.
        existing = tbl.search().where(f"id = '{doc_id}'", prefilter=True).limit(1).to_list()
        if not existing:
            return False
        tbl.delete(f"id = '{doc_id}'")
        tbl.add([{
            "id": doc_id,
            "content": content,
            "vector": [float(v) for v in embedding],
            "metadata": json.dumps(metadata),
        }])
        return True

    def delete(self, collection: str, doc_id: str) -> bool:
        """Remove a single document. Returns True if it existed, False otherwise."""
        tbl = self._get_table(collection)
        existing = tbl.search().where(f"id = '{doc_id}'", prefilter=True).limit(1).to_list()
        if not existing:
            return False
        tbl.delete(f"id = '{doc_id}'")
        return True

    # ── Query ─────────────────────────────────────────────────────────────────

    def search(
        self,
        collection: str,
        query_embedding: list[float],
        limit: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """Nearest-neighbour search using a pre-computed query vector.

        LanceDB uses cosine distance in [0, 1]. We convert to similarity via
        ``1 - distance`` so that 1.0 = perfect match, 0.0 = orthogonal.

        ``filters`` is applied as a post-filter WHERE clause. Only simple
        equality filters (``{field: value}``) against the metadata JSON string
        are supported via a LIKE match.
        """
        tbl = self._get_table(collection)
        if tbl.count_rows() == 0:
            return []

        n = min(limit, tbl.count_rows())
        query = tbl.search([float(v) for v in query_embedding]).metric("cosine").limit(n)

        if filters:
            # Build a simple LIKE filter against the serialised metadata string.
            # This handles single-key equality; complex filters are not supported.
            clauses = [
                f"metadata LIKE '%\"{k}\": \"{v}\"%' OR metadata LIKE '%\"{k}\":{v}%'"
                for k, v in filters.items()
            ]
            where_clause = " AND ".join(f"({c})" for c in clauses)
            query = query.where(where_clause)

        rows = query.to_list()

        out: list[dict] = []
        for row in rows:
            distance = row.get("_distance", 1.0)
            similarity = max(0.0, 1.0 - distance)
            doc = self._row_to_doc(row)
            doc["similarity"] = similarity
            out.append(doc)
        return out

    def get(self, collection: str, doc_id: str) -> dict | None:
        """Retrieve a single document by ID. Returns None if not found."""
        tbl = self._get_table(collection)
        rows = tbl.search().where(f"id = '{doc_id}'", prefilter=True).limit(1).to_list()
        if not rows:
            return None
        return self._row_to_doc(rows[0])

    # ── Inspection ────────────────────────────────────────────────────────────

    def collection_count(self, collection: str) -> int:
        """Return document count, or 0 if the collection does not exist."""
        db = self._require_db()
        if collection not in db.table_names():
            return 0
        try:
            return db.open_table(collection).count_rows()
        except Exception:
            return 0

    def collection_peek(self, collection: str, limit: int = 5) -> list[dict]:
        """Return a sample of documents from the collection without searching."""
        db = self._require_db()
        if collection not in db.table_names():
            return []
        try:
            tbl = db.open_table(collection)
        except Exception:
            return []
        if tbl.count_rows() == 0:
            return []
        n = min(limit, tbl.count_rows())
        rows = tbl.head(n).to_pylist()
        return [self._row_to_doc(row) for row in rows]
