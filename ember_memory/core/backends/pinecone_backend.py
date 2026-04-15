"""Pinecone v2 storage backend for Ember Memory.

v2 backend: accepts pre-computed embedding vectors — does NOT call an
embedding function internally. Callers (EmbeddingProvider → search.py) are
responsible for producing vectors before calling insert/search.

Pinecone is cloud-only and uses a single index with NAMESPACES to isolate
collections. Document content is stored inside vector metadata because
Pinecone does not persist raw text natively.

Cosine similarity scores returned by Pinecone are already in [0, 1], so no
normalisation is required.
"""

from __future__ import annotations

from typing import Any

from ember_memory.core.backends.base import MemoryBackend

# Metadata namespace used to track collection registration (dimension, description).
_COLLECTIONS_META_NAMESPACE = "__ember_collections__"
# Sentinel vector ID used to store collection registration metadata.
_COLLECTION_META_DOC_PREFIX = "__meta__"


class PineconeBackend(MemoryBackend):
    """Pinecone serverless storage backend (v2 vector-native interface).

    All collections share one Pinecone index, isolated via namespaces.
    Collection metadata (dimension, description) is tracked inside a reserved
    ``__ember_collections__`` namespace so it survives process restarts.

    Args:
        api_key:    Pinecone API key (required).
        index_name: Name of the single index to use (created if absent).
        environment: Deprecated in Pinecone v3+; kept for signature compat.
                     Pass ``""`` (default) to ignore it.
    """

    def __init__(
        self,
        api_key: str,
        index_name: str = "ember-memory",
        environment: str = "",
    ) -> None:
        self._api_key = api_key
        self._index_name = index_name
        self._environment = environment
        self._pc: Any = None        # pinecone.Pinecone instance
        self._index: Any = None     # pinecone Index instance

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Initialise the Pinecone client and get/create the index.

        Raises RuntimeError if the client cannot be initialised.
        """
        try:
            from pinecone import Pinecone, ServerlessSpec  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "pinecone package is not installed. "
                "Run: pip install pinecone"
            ) from exc

        self._pc = Pinecone(api_key=self._api_key)

        if not self._pc.has_index(self._index_name):
            # Index does not exist — create it with a placeholder dimension.
            # The real dimension is enforced per-collection at the namespace level;
            # Pinecone requires the index-level dimension at creation time.
            # We default to 1536 (OpenAI ada-002) but the first
            # create_collection() call with a specific dimension will be stored
            # in collection metadata for validation by the caller.
            self._pc.create_index(
                name=self._index_name,
                dimension=1536,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )

        self._index = self._pc.Index(name=self._index_name)

    def _require_index(self) -> Any:
        if self._index is None:
            raise RuntimeError(
                "PineconeBackend.connect() must be called before using the backend."
            )
        return self._index

    # ── Collection management ─────────────────────────────────────────────────

    def create_collection(
        self,
        name: str,
        dimension: int,
        description: str | None = None,
    ) -> None:
        """Register a collection (namespace).

        Pinecone namespaces are created implicitly on the first upsert. We
        persist the dimension and optional description into a reserved metadata
        namespace so that ``list_collections()`` can surface them.

        No-op if the collection already exists.
        """
        index = self._require_index()
        meta_id = f"{_COLLECTION_META_DOC_PREFIX}{name}"

        # Check if already registered.
        try:
            result = index.fetch(
                ids=[meta_id],
                namespace=_COLLECTIONS_META_NAMESPACE,
            )
            if result and result.vectors and meta_id in result.vectors:
                return  # Already registered — idempotent.
        except Exception:
            pass  # Namespace may not exist yet; proceed to create.

        # Store a zero-vector placeholder (dimension must match the index).
        # We derive the index dimension from describe_index_stats if possible,
        # otherwise fall back to the collection's own dimension (first create wins).
        try:
            stats = index.describe_index_stats()
            index_dim = stats.dimension if stats.dimension else dimension
        except Exception:
            index_dim = dimension

        # Pinecone rejects all-zero vectors, use near-zero with one small value
        zero_vector: list[float] = [0.0] * index_dim
        zero_vector[0] = 1e-7
        meta_payload: dict = {
            "ember_collection_name": name,
            "ember_dimension": dimension,
        }
        if description:
            meta_payload["ember_description"] = description

        index.upsert(
            vectors=[{
                "id": meta_id,
                "values": zero_vector,
                "metadata": meta_payload,
            }],
            namespace=_COLLECTIONS_META_NAMESPACE,
        )

    def delete_collection(self, name: str) -> int:
        """Delete all vectors in a namespace and deregister the collection.

        Returns the vector count before deletion, or 0 if the collection
        did not exist.
        """
        index = self._require_index()
        count = self.collection_count(name)

        # Remove all vectors in the data namespace.
        try:
            index.delete(delete_all=True, namespace=name)
        except Exception:
            pass

        # Remove the metadata registration entry.
        meta_id = f"{_COLLECTION_META_DOC_PREFIX}{name}"
        try:
            index.delete(ids=[meta_id], namespace=_COLLECTIONS_META_NAMESPACE)
        except Exception:
            pass

        return count

    def list_collections(self) -> list[dict]:
        """Return registered collections with name, count, and optional metadata.

        Reads collection registrations from the reserved metadata namespace,
        then cross-references with live namespace stats for accurate counts.
        """
        index = self._require_index()

        # Build a map of namespace -> vector_count from live stats.
        ns_counts: dict[str, int] = {}
        try:
            stats = index.describe_index_stats()
            if stats.namespaces:
                for ns_name, ns_summary in stats.namespaces.items():
                    if ns_name == _COLLECTIONS_META_NAMESPACE:
                        continue
                    ns_counts[ns_name] = getattr(ns_summary, "vector_count", 0)
        except Exception:
            pass

        # Fetch all collection registration records.
        out: list[dict] = []
        try:
            # List all IDs in the metadata namespace.
            listed_ids: list[str] = []
            for page in index.list(
                prefix=_COLLECTION_META_DOC_PREFIX,
                namespace=_COLLECTIONS_META_NAMESPACE,
            ):
                # page is a list of id strings
                if isinstance(page, list):
                    listed_ids.extend(page)
                elif hasattr(page, "vectors"):
                    listed_ids.extend(
                        v.id if hasattr(v, "id") else v
                        for v in (page.vectors or [])
                    )

            if listed_ids:
                fetch_result = index.fetch(
                    ids=listed_ids,
                    namespace=_COLLECTIONS_META_NAMESPACE,
                )
                for _vec_id, vec in (fetch_result.vectors or {}).items():
                    meta = vec.metadata or {}
                    col_name = meta.get("ember_collection_name", "")
                    if not col_name:
                        continue
                    entry: dict = {
                        "name": col_name,
                        "count": ns_counts.get(col_name, 0),
                    }
                    if "ember_dimension" in meta:
                        entry["dimension"] = int(meta["ember_dimension"])
                    if "ember_description" in meta:
                        entry["description"] = meta["ember_description"]
                    out.append(entry)
        except Exception:
            # If the metadata namespace is empty or doesn't exist yet,
            # fall back to building the list from live namespace stats only.
            for ns_name, count in ns_counts.items():
                out.append({"name": ns_name, "count": count})

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
        """Insert a single document into a namespace.

        Content is stored inside the Pinecone vector metadata under the
        ``_content`` key, which is reserved and not surfaced to callers.
        """
        index = self._require_index()
        payload = {"_content": content, "_doc_id": doc_id}
        payload.update(metadata)
        index.upsert(
            vectors=[{
                "id": doc_id,
                "values": embedding,
                "metadata": payload,
            }],
            namespace=collection,
        )
        return self.collection_count(collection)

    def insert_batch(
        self,
        collection: str,
        ids: list[str],
        contents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> int:
        """Insert multiple documents in a single upsert call."""
        if not ids:
            return 0
        index = self._require_index()
        vectors = []
        for doc_id, content, embedding, meta in zip(ids, contents, embeddings, metadatas):
            payload: dict = {"_content": content, "_doc_id": doc_id}
            payload.update(meta)
            vectors.append({
                "id": doc_id,
                "values": embedding,
                "metadata": payload,
            })
        index.upsert(vectors=vectors, namespace=collection)
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

        Returns True if the document existed and was updated; False otherwise.
        Pinecone's upsert is idempotent, so we check existence first.
        """
        index = self._require_index()
        # Check existence.
        try:
            result = index.fetch(ids=[doc_id], namespace=collection)
            if not result or not result.vectors or doc_id not in result.vectors:
                return False
        except Exception:
            return False

        payload: dict = {"_content": content, "_doc_id": doc_id}
        payload.update(metadata)
        index.upsert(
            vectors=[{
                "id": doc_id,
                "values": embedding,
                "metadata": payload,
            }],
            namespace=collection,
        )
        return True

    def delete(self, collection: str, doc_id: str) -> bool:
        """Remove a single document. Returns True if it existed, False otherwise."""
        index = self._require_index()
        try:
            result = index.fetch(ids=[doc_id], namespace=collection)
            if not result or not result.vectors or doc_id not in result.vectors:
                return False
        except Exception:
            return False
        index.delete(ids=[doc_id], namespace=collection)
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

        Pinecone cosine scores are already in [0, 1], so no normalisation
        is needed.

        Args:
            collection:      Target namespace.
            query_embedding: Pre-computed query vector.
            limit:           Maximum results to return.
            filters:         Optional metadata equality filters. Converted
                             to Pinecone filter format
                             ``{field: {"$eq": value}}``.

        Returns:
            List of dicts ordered by descending similarity, each with:
            ``id``, ``content``, ``metadata``, ``similarity``.
        """
        index = self._require_index()

        pinecone_filter: dict | None = None
        if filters:
            if len(filters) == 1:
                field, value = next(iter(filters.items()))
                pinecone_filter = {field: {"$eq": value}}
            else:
                pinecone_filter = {
                    "$and": [{k: {"$eq": v}} for k, v in filters.items()]
                }

        query_kwargs: dict = {
            "vector": query_embedding,
            "top_k": limit,
            "namespace": collection,
            "include_metadata": True,
        }
        if pinecone_filter is not None:
            query_kwargs["filter"] = pinecone_filter

        try:
            response = index.query(**query_kwargs)
        except Exception:
            return []

        out: list[dict] = []
        for match in response.matches or []:
            meta = dict(match.metadata or {})
            content = meta.pop("_content", "")
            meta.pop("_doc_id", None)  # Remove internal field.
            out.append({
                "id": match.id,
                "content": content,
                "metadata": meta,
                "similarity": float(match.score),
            })
        return out

    def get(self, collection: str, doc_id: str) -> dict | None:
        """Retrieve a single document by ID. Returns None if not found."""
        index = self._require_index()
        try:
            result = index.fetch(ids=[doc_id], namespace=collection)
        except Exception:
            return None

        if not result or not result.vectors or doc_id not in result.vectors:
            return None

        vec = result.vectors[doc_id]
        meta = dict(vec.metadata or {})
        content = meta.pop("_content", "")
        meta.pop("_doc_id", None)
        return {
            "id": doc_id,
            "content": content,
            "metadata": meta,
        }

    # ── Inspection ────────────────────────────────────────────────────────────

    def collection_count(self, collection: str) -> int:
        """Return the number of documents in a namespace, or 0 if absent."""
        index = self._require_index()
        try:
            stats = index.describe_index_stats()
            ns = stats.namespaces or {}
            summary = ns.get(collection)
            if summary is None:
                return 0
            return getattr(summary, "vector_count", 0)
        except Exception:
            return 0

    def collection_peek(self, collection: str, limit: int = 5) -> list[dict]:
        """Return a sample of documents from the namespace (no search).

        Uses the ``list`` API to retrieve IDs, then fetches their full
        records. This is eventually consistent but sufficient for inspection.
        """
        index = self._require_index()
        try:
            ids: list[str] = []
            for page in index.list(namespace=collection):
                if isinstance(page, list):
                    ids.extend(page)
                elif hasattr(page, "vectors"):
                    ids.extend(
                        v.id if hasattr(v, "id") else v
                        for v in (page.vectors or [])
                    )
                if len(ids) >= limit:
                    break
            ids = ids[:limit]
        except Exception:
            return []

        if not ids:
            return []

        try:
            result = index.fetch(ids=ids, namespace=collection)
        except Exception:
            return []

        out: list[dict] = []
        for vec_id in ids:
            if not result.vectors or vec_id not in result.vectors:
                continue
            vec = result.vectors[vec_id]
            meta = dict(vec.metadata or {})
            content = meta.pop("_content", "")
            meta.pop("_doc_id", None)
            out.append({
                "id": vec_id,
                "content": content,
                "metadata": meta,
            })
        return out
