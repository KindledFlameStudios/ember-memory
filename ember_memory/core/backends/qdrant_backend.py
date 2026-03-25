"""Qdrant v2 storage backend for Ember Memory.

v2 backend: accepts pre-computed embedding vectors — does NOT call an
embedding function internally. Callers (EmbeddingProvider → search.py) are
responsible for producing vectors before calling insert/search.

Qdrant's cosine similarity scores are in [-1, 1]. We normalise to [0, 1]
via ``(score + 1) / 2``.

Qdrant point IDs must be either unsigned integers or UUIDs. Since ember-memory
uses arbitrary string doc IDs, we map them deterministically to UUID v5 using a
fixed namespace and store the original string in the point payload as ``doc_id``.
"""

from __future__ import annotations

import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
    VectorParams,
)

from ember_memory.core.backends.base import MemoryBackend

# Stable namespace for deterministic string → UUID v5 mapping.
_EMBER_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _to_qdrant_id(doc_id: str) -> str:
    """Convert an arbitrary string doc ID to a Qdrant-compatible UUID string."""
    return str(uuid.uuid5(_EMBER_NS, doc_id))


def _normalise_score(score: float) -> float:
    """Map Qdrant cosine score [-1, 1] to similarity [0, 1]."""
    return (score + 1.0) / 2.0


class QdrantBackend(MemoryBackend):
    """Qdrant storage backend (v2 vector-native interface).

    Supports two modes:
    - **Server mode** (default): connects to a running Qdrant instance via HTTP
      or gRPC. Pass ``url`` and optionally ``api_key``/``prefer_grpc``.
    - **In-memory mode**: pass ``in_memory=True`` for a lightweight, fully
      in-process instance. No server required — ideal for testing.
    """

    def __init__(
        self,
        url: str = "localhost:6333",
        api_key: str | None = None,
        prefer_grpc: bool = False,
        in_memory: bool = False,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._prefer_grpc = prefer_grpc
        self._in_memory = in_memory
        self._client: QdrantClient | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Initialise the QdrantClient. Must be called once after construction."""
        if self._in_memory:
            self._client = QdrantClient(":memory:")
        else:
            self._client = QdrantClient(
                url=self._url,
                api_key=self._api_key,
                prefer_grpc=self._prefer_grpc,
            )

    def _require_client(self) -> QdrantClient:
        if self._client is None:
            raise RuntimeError(
                "QdrantBackend.connect() must be called before using the backend."
            )
        return self._client

    # ── Collection management ─────────────────────────────────────────────────

    def create_collection(
        self,
        name: str,
        dimension: int,
        description: str | None = None,
    ) -> None:
        """Create a collection. No-op if it already exists."""
        client = self._require_client()
        existing = {c.name for c in client.get_collections().collections}
        if name in existing:
            return
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
        )
        # Store description as a payload index comment is not natively supported;
        # we track it in a lightweight in-memory registry instead.
        if description is not None:
            if not hasattr(self, "_descriptions"):
                self._descriptions: dict[str, str] = {}
            self._descriptions[name] = description

    def delete_collection(self, name: str) -> int:
        """Delete a collection. Returns doc count before deletion, or 0."""
        client = self._require_client()
        existing = {c.name for c in client.get_collections().collections}
        if name not in existing:
            return 0
        count = client.count(collection_name=name).count
        client.delete_collection(collection_name=name)
        # Clean up description cache if present.
        if hasattr(self, "_descriptions"):
            self._descriptions.pop(name, None)
        return count

    def list_collections(self) -> list[dict]:
        """Return list of dicts with 'name' and 'count', plus optional metadata."""
        client = self._require_client()
        collections = client.get_collections().collections
        descriptions = getattr(self, "_descriptions", {})
        out: list[dict] = []
        for col_desc in collections:
            name = col_desc.name
            try:
                count = client.count(collection_name=name).count
            except Exception:
                count = 0
            entry: dict = {"name": name, "count": count}
            if name in descriptions:
                entry["description"] = descriptions[name]
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
        """Insert a single document with a pre-computed embedding vector."""
        client = self._require_client()
        payload = {"content": content, "doc_id": doc_id, **metadata}
        client.upsert(
            collection_name=collection,
            points=[PointStruct(id=_to_qdrant_id(doc_id), vector=embedding, payload=payload)],
        )
        return client.count(collection_name=collection).count

    def insert_batch(
        self,
        collection: str,
        ids: list[str],
        contents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> int:
        """Insert multiple documents in a single Qdrant upsert call."""
        if not ids:
            return 0
        client = self._require_client()
        points = [
            PointStruct(
                id=_to_qdrant_id(doc_id),
                vector=embedding,
                payload={"content": content, "doc_id": doc_id, **meta},
            )
            for doc_id, content, embedding, meta in zip(ids, contents, embeddings, metadatas)
        ]
        client.upsert(collection_name=collection, points=points)
        return len(ids)

    def update(
        self,
        collection: str,
        doc_id: str,
        content: str,
        embedding: list[float],
        metadata: dict,
    ) -> bool:
        """Replace a document's content, vector, and metadata in-place.

        Returns True if found and updated, False if the document does not exist.
        """
        client = self._require_client()
        qdrant_id = _to_qdrant_id(doc_id)
        existing = client.retrieve(
            collection_name=collection, ids=[qdrant_id], with_payload=False
        )
        if not existing:
            return False
        payload = {"content": content, "doc_id": doc_id, **metadata}
        client.upsert(
            collection_name=collection,
            points=[PointStruct(id=qdrant_id, vector=embedding, payload=payload)],
        )
        return True

    def delete(self, collection: str, doc_id: str) -> bool:
        """Remove a single document. Returns True if it existed, False otherwise."""
        client = self._require_client()
        qdrant_id = _to_qdrant_id(doc_id)
        existing = client.retrieve(
            collection_name=collection, ids=[qdrant_id], with_payload=False
        )
        if not existing:
            return False
        client.delete(
            collection_name=collection,
            points_selector=PointIdsList(points=[qdrant_id]),
        )
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

        Qdrant returns cosine scores in [-1, 1]. We normalise to [0, 1] via
        ``(score + 1) / 2``.

        Args:
            collection:      Target collection.
            query_embedding: Pre-computed query vector.
            limit:           Maximum results to return.
            filters:         Optional metadata equality filter, e.g. ``{"tag": "foo"}``.
                             Converted to a Qdrant ``Filter`` with ``must`` clauses.

        Returns:
            List of dicts ordered by descending similarity, each with:
            ``id``, ``content``, ``metadata``, ``similarity``.
        """
        client = self._require_client()
        count = client.count(collection_name=collection).count
        if count == 0:
            return []

        query_filter: Filter | None = None
        if filters:
            must_conditions = [
                FieldCondition(key=field, match=MatchValue(value=value))
                for field, value in filters.items()
            ]
            query_filter = Filter(must=must_conditions)

        results = client.query_points(
            collection_name=collection,
            query=query_embedding,
            limit=min(limit, count),
            query_filter=query_filter,
            with_payload=True,
        )

        out: list[dict] = []
        for point in results.points:
            payload = point.payload or {}
            content = payload.pop("content", "")
            # Remove the internal doc_id field we injected — surface it as 'id'
            original_id = payload.pop("doc_id", "")
            out.append({
                "id": original_id,
                "content": content,
                "metadata": payload,
                "similarity": _normalise_score(point.score),
            })
        return out

    def get(self, collection: str, doc_id: str) -> dict | None:
        """Retrieve a single document by ID. Returns None if not found."""
        client = self._require_client()
        points = client.retrieve(
            collection_name=collection,
            ids=[_to_qdrant_id(doc_id)],
            with_payload=True,
        )
        if not points:
            return None
        payload = dict(points[0].payload or {})
        content = payload.pop("content", "")
        payload.pop("doc_id", None)  # Remove internal field
        return {
            "id": doc_id,
            "content": content,
            "metadata": payload,
        }

    # ── Inspection ────────────────────────────────────────────────────────────

    def collection_count(self, collection: str) -> int:
        """Return document count for a collection, or 0 if it does not exist."""
        client = self._require_client()
        try:
            return client.count(collection_name=collection).count
        except Exception:
            return 0

    def collection_peek(self, collection: str, limit: int = 5) -> list[dict]:
        """Return a sample of documents from the collection (no search)."""
        client = self._require_client()
        try:
            count = client.count(collection_name=collection).count
        except Exception:
            return []
        if count == 0:
            return []

        points, _ = client.scroll(
            collection_name=collection,
            limit=min(limit, count),
            with_payload=True,
        )

        out: list[dict] = []
        for point in points:
            payload = dict(point.payload or {})
            content = payload.pop("content", "")
            original_id = payload.pop("doc_id", "")
            out.append({
                "id": original_id,
                "content": content,
                "metadata": payload,
            })
        return out
