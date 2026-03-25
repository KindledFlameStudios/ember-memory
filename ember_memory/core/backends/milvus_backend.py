"""Milvus v2 storage backend for Ember Memory.

v2 backend: accepts pre-computed embedding vectors — does NOT call an
embedding function internally. Callers (EmbeddingProvider → search.py) are
responsible for producing vectors before calling insert/search.

Milvus returns cosine distances in [0, 2] for IP/COSINE metric depending on
the version and search configuration. The MilvusClient high-level API returns
distances as floats — for COSINE metric these are already cosine similarities
in [-1, 1] (normalised internally). We normalise to [0, 1] via
``(score + 1) / 2`` to match the MemoryBackend contract.

Connection: supports both a self-hosted Milvus server (default
``http://localhost:19530``) and Zilliz Cloud (pass the cloud endpoint as
``uri`` and your API key as ``token``).
"""

from __future__ import annotations

import json

from pymilvus import MilvusClient, DataType

from ember_memory.core.backends.base import MemoryBackend

# Fields stored in every collection.
_FIELD_ID = "id"
_FIELD_CONTENT = "content"
_FIELD_METADATA = "metadata"
_FIELD_EMBEDDING = "embedding"

# Maximum VARCHAR length for Milvus (hard ceiling is 65535 bytes).
_MAX_VARCHAR = 65535

# HNSW index parameters for the embedding field.
_HNSW_INDEX_PARAMS = {"M": 16, "efConstruction": 256}
_HNSW_SEARCH_PARAMS = {"ef": 128}


def _normalise_score(score: float) -> float:
    """Map Milvus cosine similarity score [-1, 1] → [0, 1]."""
    return max(0.0, min(1.0, (score + 1.0) / 2.0))


class MilvusBackend(MemoryBackend):
    """Milvus storage backend (v2 vector-native interface).

    Uses the ``MilvusClient`` high-level API from pymilvus ≥ 2.3.

    Supports two deployment targets:
    - **Self-hosted Milvus** (default): ``uri="http://localhost:19530"``
    - **Zilliz Cloud**: pass your cloud endpoint as ``uri`` and your API
      key / JWT token as ``token``.

    Args:
        uri:     Milvus server address or Zilliz Cloud endpoint.
        token:   API key for Zilliz Cloud, or ``"user:password"`` for
                 Milvus with authentication enabled. Empty for unauthenticated
                 local deployments.
        db_name: Database to operate on. Defaults to ``"ember_memory"``.
                 The database must exist (Milvus creates ``"default"`` on
                 startup; you may need to create ``ember_memory`` first or
                 pass ``db_name="default"``).
    """

    def __init__(
        self,
        uri: str = "http://localhost:19530",
        token: str = "",
        db_name: str = "ember_memory",
    ) -> None:
        self._uri = uri
        self._token = token
        self._db_name = db_name
        self._client: MilvusClient | None = None
        # Local cache of {collection_name: dimension} so we can rebuild the
        # schema on demand without re-querying the server every call.
        self._dimensions: dict[str, int] = {}
        # Optional description cache — Milvus doesn't support arbitrary
        # collection-level metadata, so we track it in memory.
        self._descriptions: dict[str, str] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Open the connection to Milvus.

        Creates the target database if it does not exist (best-effort — some
        deployments restrict DDL for the default user). Raises ``RuntimeError``
        if the server is unreachable.
        """
        kwargs: dict = {"uri": self._uri}
        if self._token:
            kwargs["token"] = self._token

        try:
            client = MilvusClient(**kwargs)
        except Exception as exc:
            raise RuntimeError(
                f"MilvusBackend: failed to connect to {self._uri!r}: {exc}"
            ) from exc

        # Attempt to switch to (or create) the target database.
        if self._db_name and self._db_name != "default":
            try:
                existing_dbs = client.list_databases()
                if self._db_name not in existing_dbs:
                    client.create_database(self._db_name)
                client.using_database(self._db_name)
            except Exception:
                # Non-fatal: some Milvus lite / Zilliz setups don't expose DB ops.
                pass

        self._client = client

    def _require_client(self) -> MilvusClient:
        if self._client is None:
            raise RuntimeError(
                "MilvusBackend.connect() must be called before using the backend."
            )
        return self._client

    # ── Collection management ─────────────────────────────────────────────────

    def create_collection(
        self,
        name: str,
        dimension: int,
        description: str | None = None,
    ) -> None:
        """Create a collection with an HNSW index on the embedding field.

        No-op if the collection already exists.
        """
        client = self._require_client()

        if client.has_collection(name):
            return

        # Build schema explicitly so we control every field.
        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(
            field_name=_FIELD_ID,
            datatype=DataType.VARCHAR,
            max_length=512,
            is_primary=True,
        )
        schema.add_field(
            field_name=_FIELD_CONTENT,
            datatype=DataType.VARCHAR,
            max_length=_MAX_VARCHAR,
        )
        schema.add_field(
            field_name=_FIELD_METADATA,
            datatype=DataType.VARCHAR,
            max_length=_MAX_VARCHAR,
        )
        schema.add_field(
            field_name=_FIELD_EMBEDDING,
            datatype=DataType.FLOAT_VECTOR,
            dim=dimension,
        )

        # HNSW index with cosine metric on the embedding field.
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name=_FIELD_EMBEDDING,
            index_type="HNSW",
            metric_type="COSINE",
            params=_HNSW_INDEX_PARAMS,
        )

        client.create_collection(
            collection_name=name,
            schema=schema,
            index_params=index_params,
        )

        self._dimensions[name] = dimension
        if description is not None:
            self._descriptions[name] = description

    def delete_collection(self, name: str) -> int:
        """Delete a collection and return the pre-deletion document count."""
        client = self._require_client()
        if not client.has_collection(name):
            return 0
        count = self._get_count(client, name)
        client.drop_collection(name)
        self._dimensions.pop(name, None)
        self._descriptions.pop(name, None)
        return count

    def list_collections(self) -> list[dict]:
        """Return a list of dicts, each with ``name`` and ``count``."""
        client = self._require_client()
        names: list[str] = client.list_collections()
        out: list[dict] = []
        for name in names:
            count = self._get_count(client, name)
            entry: dict = {"name": name, "count": count}
            if name in self._descriptions:
                entry["description"] = self._descriptions[name]
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
        """Insert a single document. Returns the new collection document count."""
        client = self._require_client()
        client.insert(
            collection_name=collection,
            data={
                _FIELD_ID: doc_id,
                _FIELD_CONTENT: content,
                _FIELD_METADATA: json.dumps(metadata),
                _FIELD_EMBEDDING: embedding,
            },
        )
        return self._get_count(client, collection)

    def insert_batch(
        self,
        collection: str,
        ids: list[str],
        contents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> int:
        """Insert multiple documents in a single call. Returns the insert count."""
        if not ids:
            return 0
        client = self._require_client()
        records = [
            {
                _FIELD_ID: doc_id,
                _FIELD_CONTENT: content,
                _FIELD_METADATA: json.dumps(meta),
                _FIELD_EMBEDDING: emb,
            }
            for doc_id, content, emb, meta in zip(ids, contents, embeddings, metadatas)
        ]
        client.insert(collection_name=collection, data=records)
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

        Returns True if found and updated, False if the document did not exist.
        """
        client = self._require_client()
        existing = client.get(collection_name=collection, ids=[doc_id])
        if not existing:
            return False
        client.upsert(
            collection_name=collection,
            data={
                _FIELD_ID: doc_id,
                _FIELD_CONTENT: content,
                _FIELD_METADATA: json.dumps(metadata),
                _FIELD_EMBEDDING: embedding,
            },
        )
        return True

    def delete(self, collection: str, doc_id: str) -> bool:
        """Remove a single document. Returns True if it existed, False otherwise."""
        client = self._require_client()
        existing = client.get(collection_name=collection, ids=[doc_id])
        if not existing:
            return False
        client.delete(collection_name=collection, ids=[doc_id])
        return True

    # ── Query ─────────────────────────────────────────────────────────────────

    def search(
        self,
        collection: str,
        query_embedding: list[float],
        limit: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """Nearest-neighbour vector search.

        Milvus COSINE metric returns scores in [-1, 1]. These are normalised to
        [0, 1] via ``(score + 1) / 2``.

        Args:
            collection:      Target collection name.
            query_embedding: Pre-computed query vector.
            limit:           Maximum results to return.
            filters:         Optional equality filters, e.g. ``{"source": "web"}``.
                             Translated to a Milvus boolean expression.

        Returns:
            List of dicts ordered by descending similarity, each with
            ``id``, ``content``, ``metadata``, ``similarity``.
        """
        client = self._require_client()

        filter_expr = _build_filter_expr(filters) if filters else ""

        raw_results: list[list[dict]] = client.search(
            collection_name=collection,
            data=[query_embedding],
            anns_field=_FIELD_EMBEDDING,
            limit=limit,
            output_fields=[_FIELD_ID, _FIELD_CONTENT, _FIELD_METADATA],
            search_params=_HNSW_SEARCH_PARAMS,
            filter=filter_expr,
        )

        out: list[dict] = []
        for hit in raw_results[0]:
            entity = hit.get("entity", hit)
            raw_meta = entity.get(_FIELD_METADATA, "{}")
            try:
                meta = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
            except (json.JSONDecodeError, TypeError):
                meta = {}
            out.append({
                "id": entity.get(_FIELD_ID, hit.get("id", "")),
                "content": entity.get(_FIELD_CONTENT, ""),
                "metadata": meta,
                "similarity": _normalise_score(hit.get("distance", 0.0)),
            })
        return out

    def get(self, collection: str, doc_id: str) -> dict | None:
        """Retrieve a single document by ID. Returns None if not found."""
        client = self._require_client()
        results = client.get(
            collection_name=collection,
            ids=[doc_id],
            output_fields=[_FIELD_ID, _FIELD_CONTENT, _FIELD_METADATA],
        )
        if not results:
            return None
        entity = results[0]
        raw_meta = entity.get(_FIELD_METADATA, "{}")
        try:
            meta = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
        except (json.JSONDecodeError, TypeError):
            meta = {}
        return {
            "id": entity.get(_FIELD_ID, doc_id),
            "content": entity.get(_FIELD_CONTENT, ""),
            "metadata": meta,
        }

    # ── Inspection ────────────────────────────────────────────────────────────

    def collection_count(self, collection: str) -> int:
        """Return document count for a collection, or 0 if it does not exist."""
        client = self._require_client()
        if not client.has_collection(collection):
            return 0
        return self._get_count(client, collection)

    def collection_peek(self, collection: str, limit: int = 5) -> list[dict]:
        """Return a sample of documents without performing a search."""
        client = self._require_client()
        if not client.has_collection(collection):
            return []
        try:
            results = client.query(
                collection_name=collection,
                filter="",
                output_fields=[_FIELD_ID, _FIELD_CONTENT, _FIELD_METADATA],
                limit=limit,
            )
        except Exception:
            return []

        out: list[dict] = []
        for entity in results:
            raw_meta = entity.get(_FIELD_METADATA, "{}")
            try:
                meta = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
            except (json.JSONDecodeError, TypeError):
                meta = {}
            out.append({
                "id": entity.get(_FIELD_ID, ""),
                "content": entity.get(_FIELD_CONTENT, ""),
                "metadata": meta,
            })
        return out

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _get_count(client: MilvusClient, collection: str) -> int:
        """Return the document count for a collection, defaulting to 0 on error."""
        try:
            stats = client.get_collection_stats(collection)
            # get_collection_stats returns {"row_count": N} (or similar).
            return int(stats.get("row_count", 0))
        except Exception:
            return 0


def _build_filter_expr(filters: dict) -> str:
    """Convert a simple ``{field: value}`` dict into a Milvus filter expression.

    Only equality matching is supported. Multiple key/value pairs are joined
    with ``and``.

    For JSON-serialised metadata fields, the filter targets the ``metadata``
    VARCHAR column as a raw string match, which is limited. More complex
    filtering should use Milvus JSON path expressions directly.
    """
    clauses: list[str] = []
    for field, value in filters.items():
        if isinstance(value, str):
            safe = value.replace('"', '\\"')
            clauses.append(f'{field} == "{safe}"')
        else:
            clauses.append(f"{field} == {value}")
    return " and ".join(clauses)
