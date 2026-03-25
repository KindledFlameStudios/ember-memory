"""ChromaDB v2 storage backend for Ember Memory.

v2 backend: accepts pre-computed embedding vectors — does NOT call an
embedding function internally. Callers (EmbeddingProvider → search.py) are
responsible for producing vectors before calling insert/search.

Similarity values are normalised from ChromaDB's cosine distance [0, 2]
to similarity [0, 1] via ``max(0, 1 - distance)``.
"""

from __future__ import annotations

import chromadb
from ember_memory.core.backends.base import MemoryBackend


class ChromaBackendV2(MemoryBackend):
    """ChromaDB persistent storage backend (v2 vector-native interface)."""

    def __init__(self, data_dir: str) -> None:
        self._data_dir = data_dir
        self._client: chromadb.PersistentClient | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Initialise the PersistentClient. Must be called once after construction."""
        self._client = chromadb.PersistentClient(path=self._data_dir)

    def _require_client(self) -> chromadb.PersistentClient:
        if self._client is None:
            raise RuntimeError(
                "ChromaBackendV2.connect() must be called before using the backend."
            )
        return self._client

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _sanitise_metadata(metadata: dict) -> dict | None:
        """Return None for empty dicts — ChromaDB rejects empty metadata."""
        return metadata if metadata else None

    def _get_collection(self, name: str):
        """Retrieve an existing collection by name.  Raises if not found."""
        client = self._require_client()
        return client.get_collection(name=name)

    def _get_or_create_collection(self, name: str, metadata: dict | None = None):
        """Get or create a collection (used internally for idempotent ops)."""
        client = self._require_client()
        return client.get_or_create_collection(
            name=name,
            metadata=metadata or {"hnsw:space": "cosine"},
        )

    # ── Collection management ─────────────────────────────────────────────────

    def create_collection(
        self,
        name: str,
        dimension: int,
        description: str | None = None,
    ) -> None:
        """Create a collection. No-op if it already exists."""
        client = self._require_client()
        meta: dict = {"hnsw:space": "cosine", "dimension": dimension}
        if description:
            meta["description"] = description
        client.get_or_create_collection(name=name, metadata=meta)

    def delete_collection(self, name: str) -> int:
        """Delete a collection. Returns doc count before deletion, or 0."""
        client = self._require_client()
        try:
            col = client.get_collection(name=name)
            count = col.count()
        except Exception:
            return 0
        client.delete_collection(name=name)
        return count

    def list_collections(self) -> list[dict]:
        """Return list of dicts with 'name', 'count', and optional metadata."""
        client = self._require_client()
        collections = client.list_collections()
        out: list[dict] = []
        for col_obj in collections:
            col_name = col_obj.name if hasattr(col_obj, "name") else str(col_obj)
            try:
                col = client.get_collection(col_name)
                count = col.count()
                meta = col.metadata or {}
            except Exception:
                count = 0
                meta = {}
            entry: dict = {"name": col_name, "count": count}
            if "description" in meta:
                entry["description"] = meta["description"]
            if "dimension" in meta:
                entry["dimension"] = meta["dimension"]
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
        col = self._get_collection(collection)
        col.add(
            ids=[doc_id],
            documents=[content],
            embeddings=[embedding],
            metadatas=[self._sanitise_metadata(metadata)],
        )
        return col.count()

    def insert_batch(
        self,
        collection: str,
        ids: list[str],
        contents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> int:
        """Insert multiple documents in a single ChromaDB call."""
        if not ids:
            return 0
        col = self._get_collection(collection)
        sanitised = [self._sanitise_metadata(m) for m in metadatas]
        col.add(
            ids=ids,
            documents=contents,
            embeddings=embeddings,
            metadatas=sanitised,
        )
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
        col = self._get_collection(collection)
        existing = col.get(ids=[doc_id])
        if not existing["ids"]:
            return False
        col.update(
            ids=[doc_id],
            documents=[content],
            embeddings=[embedding],
            metadatas=[self._sanitise_metadata(metadata)],
        )
        return True

    def delete(self, collection: str, doc_id: str) -> bool:
        """Remove a single document. Returns True if it existed, False otherwise."""
        col = self._get_collection(collection)
        existing = col.get(ids=[doc_id])
        if not existing["ids"]:
            return False
        col.delete(ids=[doc_id])
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

        ChromaDB uses cosine distance in [0, 2]. We convert to similarity in
        [0, 1] via ``max(0, 1 - distance)``.

        Args:
            collection:      Target collection.
            query_embedding: Pre-computed query vector.
            limit:           Maximum results to return.
            filters:         Optional metadata equality filter, e.g. ``{"tag": "foo"}``.
                             Converted to ChromaDB's ``where={field: {"$eq": value}}``
                             format for single key/value pairs, or passed through
                             directly if already in ChromaDB ``where`` format.

        Returns:
            List of dicts ordered by descending similarity, each with:
            ``id``, ``content``, ``metadata``, ``similarity``.
        """
        col = self._get_collection(collection)
        count = col.count()
        if count == 0:
            return []

        n = min(limit, count)

        # Build where clause from filters
        where = None
        if filters:
            # If the caller passed a single flat {field: value} dict, convert it.
            # If it already contains ChromaDB operators (keys start with '$'), pass through.
            if all(not k.startswith("$") for k in filters):
                if len(filters) == 1:
                    field, value = next(iter(filters.items()))
                    where = {field: {"$eq": value}}
                else:
                    # Multiple equality conditions — use $and
                    where = {"$and": [{k: {"$eq": v}} for k, v in filters.items()]}
            else:
                where = filters

        query_kwargs: dict = {
            "query_embeddings": [query_embedding],
            "n_results": n,
            "include": ["documents", "metadatas", "distances"],
        }
        if where is not None:
            query_kwargs["where"] = where

        results = col.query(**query_kwargs)

        out: list[dict] = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, doc_id in enumerate(ids):
            distance = distances[i] if i < len(distances) else 1.0
            similarity = max(0.0, 1.0 - distance)
            out.append({
                "id": doc_id,
                "content": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if metas and i < len(metas) else {},
                "similarity": similarity,
            })
        return out

    def get(self, collection: str, doc_id: str) -> dict | None:
        """Retrieve a single document by ID. Returns None if not found."""
        col = self._get_collection(collection)
        result = col.get(ids=[doc_id], include=["documents", "metadatas"])
        if not result["ids"]:
            return None
        return {
            "id": result["ids"][0],
            "content": result["documents"][0] if result["documents"] else "",
            "metadata": result["metadatas"][0] if result["metadatas"] else {},
        }

    # ── Inspection ────────────────────────────────────────────────────────────

    def collection_count(self, collection: str) -> int:
        """Return document count for a collection, or 0 if it does not exist."""
        try:
            col = self._get_collection(collection)
            return col.count()
        except Exception:
            return 0

    def collection_peek(self, collection: str, limit: int = 5) -> list[dict]:
        """Return a sample of documents from the collection (no search)."""
        try:
            col = self._get_collection(collection)
        except Exception:
            return []

        count = col.count()
        if count == 0:
            return []

        peek = col.peek(limit=min(limit, count))
        out: list[dict] = []
        for i, doc_id in enumerate(peek["ids"]):
            out.append({
                "id": doc_id,
                "content": peek["documents"][i] if peek.get("documents") else "",
                "metadata": peek["metadatas"][i] if peek.get("metadatas") else {},
            })
        return out
