"""Weaviate v4 storage backend for Ember Memory.

v2 backend: accepts pre-computed embedding vectors — does NOT call an
embedding function internally. Callers (EmbeddingProvider → search.py) are
responsible for producing vectors before calling insert/search.

Weaviate uses "collections" (called "classes" in older docs) as namespaces.
Collection names must be valid class identifiers: first letter capitalised,
hyphens replaced with underscores.

Similarity: Weaviate near_vector returns ``certainty`` in [0, 1] which maps
directly to cosine similarity. We use it as-is (higher = more similar).

UUID mapping: Weaviate objects are addressed by UUID. We derive a
deterministic UUID5 from each doc_id so the mapping is stable and
reversible within a session.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import weaviate
import weaviate.classes.config as wcc
import weaviate.classes.query as wcq
from weaviate.collections.classes.data import DataObject

from ember_memory.core.backends.base import MemoryBackend

if TYPE_CHECKING:
    from weaviate.client import WeaviateClient


# Namespace UUID used for all doc_id → UUID conversions.
_UUID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # UUID v1 RFC-4122 DNS ns


def _class_name(collection: str) -> str:
    """Map a collection name to a valid Weaviate class name.

    Rules applied:
    - Capitalise the first letter (Weaviate requires this).
    - Replace hyphens with underscores (hyphens are invalid in class names).
    """
    name = collection.replace("-", "_")
    return name[0].upper() + name[1:] if name else name


def _doc_uuid(doc_id: str) -> str:
    """Return a deterministic UUID string derived from ``doc_id``."""
    return str(uuid.uuid5(_UUID_NAMESPACE, doc_id))


class WeaviateBackend(MemoryBackend):
    """Weaviate persistent storage backend (v2 vector-native interface).

    Supports both local Docker deployments and Weaviate Cloud (WCD).
    Provide only ``url`` for local mode; add ``api_key`` for cloud mode.

    Args:
        url:      Weaviate server URL (default: ``"http://localhost:8080"``).
        api_key:  Optional API key for Weaviate Cloud authentication.
        grpc_port: gRPC port used by the v4 client (default: ``50051``).
    """

    def __init__(
        self,
        url: str = "http://localhost:8080",
        api_key: str | None = None,
        grpc_port: int = 50051,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._grpc_port = grpc_port
        self._client: WeaviateClient | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Open and verify the connection to Weaviate.

        Uses ``connect_to_weaviate_cloud`` when an API key is supplied,
        otherwise ``connect_to_local`` (Docker / bare-metal).

        Raises:
            RuntimeError: If the connection cannot be established or the
                          server is not ready.
        """
        if self._api_key:
            self._client = weaviate.connect_to_weaviate_cloud(
                cluster_url=self._url,
                auth_credentials=weaviate.classes.init.Auth.api_key(self._api_key),
            )
        else:
            # Parse host and port from the url for local connections.
            url = self._url.rstrip("/")
            # Strip scheme
            if "://" in url:
                url = url.split("://", 1)[1]
            if ":" in url:
                host, port_str = url.rsplit(":", 1)
                port = int(port_str)
            else:
                host = url
                port = 8080

            self._client = weaviate.connect_to_local(
                host=host,
                port=port,
                grpc_port=self._grpc_port,
            )

        if not self._client.is_ready():
            self._client.close()
            self._client = None
            raise RuntimeError(
                f"Weaviate server at {self._url} is not ready. "
                "Ensure the server is running and reachable."
            )

    def _require_client(self) -> WeaviateClient:
        """Return the active client or raise if connect() was not called."""
        if self._client is None:
            raise RuntimeError(
                "WeaviateBackend.connect() must be called before using the backend."
            )
        return self._client

    def close(self) -> None:
        """Close the Weaviate connection and release resources."""
        if self._client is not None:
            self._client.close()
            self._client = None

    # ── Collection management ─────────────────────────────────────────────────

    def create_collection(
        self,
        name: str,
        dimension: int,
        description: str | None = None,
    ) -> None:
        """Create a Weaviate collection with vectorizer set to ``none``.

        No-op if the collection already exists. Vectors are provided
        externally at insert time (we manage embeddings ourselves).

        Args:
            name:        Collection identifier (mapped to a Weaviate class name).
            dimension:   Vector dimensionality (stored as a description
                         annotation; Weaviate does not enforce it at the schema level).
            description: Optional human-readable description.
        """
        client = self._require_client()
        class_name = _class_name(name)

        if client.collections.exists(class_name):
            return  # idempotent

        properties = [
            wcc.Property(name="content", data_type=wcc.DataType.TEXT),
            wcc.Property(name="doc_id", data_type=wcc.DataType.TEXT),
            wcc.Property(name="metadata", data_type=wcc.DataType.TEXT),
            wcc.Property(name="dimension", data_type=wcc.DataType.INT),
        ]

        client.collections.create(
            name=class_name,
            description=description,
            vectorizer_config=wcc.Configure.Vectorizer.none(),
            vector_index_config=wcc.Configure.VectorIndex.hnsw(
                distance_metric=wcc.VectorDistances.COSINE,
            ),
            properties=properties,
        )

    def delete_collection(self, name: str) -> int:
        """Delete a collection and all its documents.

        Returns:
            The number of documents that were in the collection, or 0 if
            the collection did not exist.
        """
        client = self._require_client()
        class_name = _class_name(name)

        if not client.collections.exists(class_name):
            return 0

        count = self._count_class(client, class_name)
        client.collections.delete(class_name)
        return count

    def list_collections(self) -> list[dict]:
        """Return a list of all collections with name, count, and metadata."""
        client = self._require_client()
        collections = client.collections.list_all()
        out: list[dict] = []
        for class_name, config in collections.items():
            count = self._count_class(client, class_name)
            entry: dict = {"name": class_name, "count": count}
            if config.description:
                entry["description"] = config.description
            out.append(entry)
        return out

    def _count_class(self, client: WeaviateClient, class_name: str) -> int:
        """Return the total number of objects in a Weaviate class."""
        try:
            col = client.collections.get(class_name)
            result = col.aggregate.over_all(total_count=True)
            return result.total_count or 0
        except Exception:
            return 0

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

        Returns:
            The collection's new total document count after the insert.
        """
        import json

        client = self._require_client()
        class_name = _class_name(collection)
        col = client.collections.get(class_name)

        col.data.insert(
            properties={
                "doc_id": doc_id,
                "content": content,
                "metadata": json.dumps(metadata),
            },
            uuid=_doc_uuid(doc_id),
            vector=embedding,
        )
        return self._count_class(client, class_name)

    def insert_batch(
        self,
        collection: str,
        ids: list[str],
        contents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> int:
        """Insert multiple documents using Weaviate's bulk insert.

        Returns:
            The number of documents successfully inserted.
        """
        import json

        if not ids:
            return 0

        client = self._require_client()
        class_name = _class_name(collection)
        col = client.collections.get(class_name)

        objects = [
            DataObject(
                properties={
                    "doc_id": ids[i],
                    "content": contents[i],
                    "metadata": json.dumps(metadatas[i]),
                },
                uuid=_doc_uuid(ids[i]),
                vector=embeddings[i],
            )
            for i in range(len(ids))
        ]

        result = col.data.insert_many(objects)
        # Count errors vs successes
        errors = len(result.errors) if result.errors else 0
        return len(ids) - errors

    def update(
        self,
        collection: str,
        doc_id: str,
        content: str,
        embedding: list[float],
        metadata: dict,
    ) -> bool:
        """Replace a document's content, vector, and metadata in-place.

        Returns:
            True if the document was found and updated, False if it did not exist.
        """
        import json

        client = self._require_client()
        class_name = _class_name(collection)
        col = client.collections.get(class_name)
        obj_uuid = _doc_uuid(doc_id)

        if not col.data.exists(obj_uuid):
            return False

        col.data.replace(
            uuid=obj_uuid,
            properties={
                "doc_id": doc_id,
                "content": content,
                "metadata": json.dumps(metadata),
            },
            vector=embedding,
        )
        return True

    def delete(self, collection: str, doc_id: str) -> bool:
        """Remove a single document from a collection.

        Returns:
            True if the document was found and deleted, False if it did not exist.
        """
        client = self._require_client()
        class_name = _class_name(collection)
        col = client.collections.get(class_name)
        obj_uuid = _doc_uuid(doc_id)

        if not col.data.exists(obj_uuid):
            return False

        return col.data.delete_by_id(obj_uuid)

    # ── Query ─────────────────────────────────────────────────────────────────

    def search(
        self,
        collection: str,
        query_embedding: list[float],
        limit: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """Nearest-neighbour search using a pre-computed query vector.

        Weaviate returns ``certainty`` in [0, 1] for cosine similarity.
        We use it directly as the similarity score (higher = more similar).

        Args:
            collection:      Target collection.
            query_embedding: Pre-computed query vector.
            limit:           Maximum results to return.
            filters:         Optional metadata equality filter ``{field: value}``.
                             Fields are matched against stored Weaviate properties.

        Returns:
            List of dicts ordered by descending similarity, each with:
            ``id``, ``content``, ``metadata``, ``similarity``.
        """
        import json

        client = self._require_client()
        class_name = _class_name(collection)
        col = client.collections.get(class_name)

        # Build weaviate filters from flat {field: value} dict
        weaviate_filter = None
        if filters:
            conditions = [
                wcq.Filter.by_property(field).equal(value)
                for field, value in filters.items()
            ]
            if len(conditions) == 1:
                weaviate_filter = conditions[0]
            else:
                weaviate_filter = wcq.Filter.all_of(conditions)

        result = col.query.near_vector(
            near_vector=query_embedding,
            limit=limit,
            return_metadata=wcq.MetadataQuery(certainty=True),
            filters=weaviate_filter,
        )

        out: list[dict] = []
        for obj in result.objects:
            props = obj.properties
            certainty = (
                obj.metadata.certainty
                if obj.metadata and obj.metadata.certainty is not None
                else 0.0
            )
            # Certainty is already in [0, 1] for cosine — use directly.
            similarity = max(0.0, min(1.0, float(certainty)))
            raw_meta = props.get("metadata", "{}")
            try:
                meta = json.loads(raw_meta) if isinstance(raw_meta, str) else {}
            except Exception:
                meta = {}
            out.append({
                "id": str(props.get("doc_id", "")),
                "content": str(props.get("content", "")),
                "metadata": meta,
                "similarity": similarity,
            })
        return out

    def get(self, collection: str, doc_id: str) -> dict | None:
        """Retrieve a single document by its ID.

        Returns:
            A dict with ``id``, ``content``, and ``metadata``, or ``None``
            if the document does not exist.
        """
        import json

        client = self._require_client()
        class_name = _class_name(collection)
        col = client.collections.get(class_name)
        obj_uuid = _doc_uuid(doc_id)

        try:
            obj = col.query.fetch_object_by_id(obj_uuid)
        except Exception:
            return None

        if obj is None:
            return None

        props = obj.properties
        raw_meta = props.get("metadata", "{}")
        try:
            meta = json.loads(raw_meta) if isinstance(raw_meta, str) else {}
        except Exception:
            meta = {}

        return {
            "id": str(props.get("doc_id", doc_id)),
            "content": str(props.get("content", "")),
            "metadata": meta,
        }

    # ── Inspection ────────────────────────────────────────────────────────────

    def collection_count(self, collection: str) -> int:
        """Return document count for a collection, or 0 if it does not exist."""
        client = self._require_client()
        class_name = _class_name(collection)
        if not client.collections.exists(class_name):
            return 0
        return self._count_class(client, class_name)

    def collection_peek(self, collection: str, limit: int = 5) -> list[dict]:
        """Return a sample of documents from the collection (no search).

        Uses Weaviate's ``fetch_objects`` for a non-search scan.
        """
        import json

        client = self._require_client()
        class_name = _class_name(collection)

        if not client.collections.exists(class_name):
            return []

        col = client.collections.get(class_name)

        try:
            result = col.query.fetch_objects(limit=limit)
        except Exception:
            return []

        out: list[dict] = []
        for obj in result.objects:
            props = obj.properties
            raw_meta = props.get("metadata", "{}")
            try:
                meta = json.loads(raw_meta) if isinstance(raw_meta, str) else {}
            except Exception:
                meta = {}
            out.append({
                "id": str(props.get("doc_id", "")),
                "content": str(props.get("content", "")),
                "metadata": meta,
            })
        return out
