"""Abstract base class for vector storage backends (v2)."""

from abc import ABC, abstractmethod


class MemoryBackend(ABC):
    """Interface that all v2 storage backends must implement.

    v2 backends are vector-native: they accept pre-computed embeddings
    rather than raw text. The caller is responsible for embedding text
    (via an EmbeddingProvider) before calling any mutating method.

    This separation means any EmbeddingProvider can be paired with any
    MemoryBackend without the backend needing to know about models, APIs,
    or embedding infrastructure.

    Similarity values returned by ``search()`` are normalised to [0, 1]
    where 1.0 is a perfect match, regardless of the underlying distance
    metric used by the backend.
    """

    @abstractmethod
    def connect(self) -> None:
        """Open and verify the connection to the backend.

        Called once after construction. Implementations should raise if
        the backend is unreachable or misconfigured.
        """
        ...

    @abstractmethod
    def create_collection(
        self,
        name: str,
        dimension: int,
        description: str | None = None,
    ) -> None:
        """Create a new collection (namespace) for documents.

        Collections are isolated namespaces. Documents in different
        collections do not interact during search.

        Args:
            name:        Unique collection identifier.
            dimension:   Vector dimensionality. Must match the embedding
                         provider in use — all inserts into this collection
                         must supply vectors of this length.
            description: Optional human-readable description stored as
                         metadata on the collection.
        """
        ...

    @abstractmethod
    def delete_collection(self, name: str) -> int:
        """Delete a collection and all its documents.

        Args:
            name: The collection to remove.

        Returns:
            The number of documents that were in the collection before
            deletion, or 0 if the collection did not exist.
        """
        ...

    @abstractmethod
    def list_collections(self) -> list[dict]:
        """List all collections managed by this backend.

        Returns:
            A list of dicts, each with at least:
            - ``"name"`` (str): Collection identifier.
            - ``"count"`` (int): Number of documents currently stored.
            Additional keys (e.g. ``"description"``, ``"dimension"``) are
            permitted but not required.
        """
        ...

    @abstractmethod
    def insert(
        self,
        collection: str,
        doc_id: str,
        content: str,
        embedding: list[float],
        metadata: dict,
    ) -> int:
        """Insert a single document into a collection.

        Args:
            collection: Target collection name.
            doc_id:     Unique document identifier within the collection.
            content:    Raw text content of the document.
            embedding:  Pre-computed vector for ``content``. Length must
                        match the collection's configured dimension.
            metadata:   Arbitrary key/value pairs stored alongside the
                        document. Values must be JSON-serialisable scalars.

        Returns:
            The collection's new total document count after the insert.
        """
        ...

    @abstractmethod
    def insert_batch(
        self,
        collection: str,
        ids: list[str],
        contents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> int:
        """Insert multiple documents in a single operation.

        All four lists must have the same length. Implementations should
        prefer a native bulk-insert API for efficiency.

        Args:
            collection: Target collection name.
            ids:        Unique document identifiers.
            contents:   Raw text content, one entry per document.
            embeddings: Pre-computed vectors, one per document.
            metadatas:  Metadata dicts, one per document.

        Returns:
            The number of documents successfully inserted.
        """
        ...

    @abstractmethod
    def search(
        self,
        collection: str,
        query_embedding: list[float],
        limit: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """Nearest-neighbour search using a pre-computed query vector.

        Args:
            collection:     Collection to search.
            query_embedding: Vector to compare against stored embeddings.
                             Length must match the collection's dimension.
            limit:          Maximum number of results to return.
            filters:        Optional metadata filters. Format is
                            backend-specific but should follow the pattern
                            ``{field: value}`` for equality matching.

        Returns:
            A list of dicts ordered by descending similarity, each with:
            - ``"id"``         (str):   Document identifier.
            - ``"content"``    (str):   Stored text content.
            - ``"metadata"``   (dict):  Stored metadata.
            - ``"similarity"`` (float): Similarity score in [0, 1].
              Higher is more similar. Implementations must normalise
              from their native metric (e.g. cosine distance → cosine
              similarity = 1 − distance).
        """
        ...

    @abstractmethod
    def get(self, collection: str, doc_id: str) -> dict | None:
        """Retrieve a single document by its ID.

        Args:
            collection: Collection to query.
            doc_id:     Document identifier.

        Returns:
            A dict with ``"id"``, ``"content"``, and ``"metadata"`` keys,
            or ``None`` if the document does not exist.
        """
        ...

    @abstractmethod
    def update(
        self,
        collection: str,
        doc_id: str,
        content: str,
        embedding: list[float],
        metadata: dict,
    ) -> bool:
        """Replace a document's content, vector, and metadata in-place.

        Args:
            collection: Collection containing the document.
            doc_id:     Document to update.
            content:    New text content.
            embedding:  New pre-computed vector for the updated content.
            metadata:   New metadata dict (replaces existing metadata entirely).

        Returns:
            True if the document was found and updated, False if it did
            not exist.
        """
        ...

    @abstractmethod
    def delete(self, collection: str, doc_id: str) -> bool:
        """Remove a single document from a collection.

        Args:
            collection: Collection containing the document.
            doc_id:     Document to remove.

        Returns:
            True if the document was found and deleted, False if it did
            not exist.
        """
        ...

    @abstractmethod
    def collection_count(self, collection: str) -> int:
        """Return the number of documents in a collection.

        Args:
            collection: Collection to count.

        Returns:
            Document count. Returns 0 if the collection does not exist.
        """
        ...

    @abstractmethod
    def collection_peek(self, collection: str, limit: int = 5) -> list[dict]:
        """Return a sample of documents from a collection without searching.

        Useful for debugging and inspection. The order of results is
        implementation-defined (typically insertion order or random).

        Args:
            collection: Collection to sample.
            limit:      Maximum number of documents to return.

        Returns:
            A list of dicts, each with ``"id"``, ``"content"``, and
            ``"metadata"`` keys.
        """
        ...
