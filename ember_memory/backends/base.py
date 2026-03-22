"""Abstract base class for storage backends."""

from abc import ABC, abstractmethod


class MemoryBackend(ABC):
    """Interface that all storage backends must implement."""

    @abstractmethod
    def store(self, doc_id: str, content: str, metadata: dict, collection: str) -> int:
        """Store a document. Returns the collection's new total count."""
        ...

    @abstractmethod
    def search(self, query: str, collection: str, n_results: int) -> list[dict]:
        """Semantic search. Returns list of {id, content, metadata, distance}."""
        ...

    @abstractmethod
    def get(self, doc_id: str, collection: str) -> dict | None:
        """Get a single document by ID. Returns {id, content, metadata} or None."""
        ...

    @abstractmethod
    def update(self, doc_id: str, content: str, metadata: dict, collection: str) -> bool:
        """Update a document. Returns True if found and updated."""
        ...

    @abstractmethod
    def delete(self, doc_id: str, collection: str) -> bool:
        """Delete a document. Returns True if found and deleted."""
        ...

    @abstractmethod
    def list_collections(self) -> list[dict]:
        """List all collections. Returns list of {name, count}."""
        ...

    @abstractmethod
    def create_collection(self, name: str, description: str | None = None) -> None:
        """Create a new collection."""
        ...

    @abstractmethod
    def delete_collection(self, name: str) -> int:
        """Delete a collection. Returns the number of entries that were in it."""
        ...

    @abstractmethod
    def collection_count(self, collection: str) -> int:
        """Return entry count for a collection."""
        ...

    @abstractmethod
    def collection_peek(self, collection: str, limit: int = 5) -> list[dict]:
        """Return a sample of entries. Returns list of {id, content, metadata}."""
        ...

    @abstractmethod
    def upsert_batch(self, ids: list[str], contents: list[str],
                     metadatas: list[dict], collection: str) -> int:
        """Batch upsert for ingestion. Returns count of documents upserted."""
        ...

    @abstractmethod
    def get_by_metadata(self, collection: str, field: str, value: str) -> list[dict]:
        """Get documents matching a metadata field. Returns list of {id, content, metadata}."""
        ...
