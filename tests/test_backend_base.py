"""
Tests for ember_memory.core.backends.base — MemoryBackend v2 abstract interface.

Verifies:
- The abstract class cannot be instantiated directly.
- An incomplete subclass (missing abstract methods) raises TypeError.
- A complete concrete subclass fulfils the interface contract.
"""

import pytest
from ember_memory.core.backends.base import MemoryBackend


# ---------------------------------------------------------------------------
# Helpers — in-memory fake backend for interface verification
# ---------------------------------------------------------------------------

class _IncompleteBackend(MemoryBackend):
    """Missing most abstract methods — must fail to instantiate."""

    def connect(self) -> None:
        pass


class _CompleteBackend(MemoryBackend):
    """Minimal in-memory backend — implements all abstract methods."""

    def __init__(self):
        # collections: {name: {"dimension": int, "description": str|None, "docs": {id: dict}}}
        self._store: dict[str, dict] = {}

    # -- lifecycle -----------------------------------------------------------

    def connect(self) -> None:
        pass  # Nothing to connect to in memory

    # -- collection management -----------------------------------------------

    def create_collection(
        self,
        name: str,
        dimension: int,
        description: str | None = None,
    ) -> None:
        if name not in self._store:
            self._store[name] = {
                "dimension": dimension,
                "description": description,
                "docs": {},
            }

    def delete_collection(self, name: str) -> int:
        if name not in self._store:
            return 0
        count = len(self._store[name]["docs"])
        del self._store[name]
        return count

    def list_collections(self) -> list[dict]:
        return [
            {"name": name, "count": len(col["docs"])}
            for name, col in self._store.items()
        ]

    # -- document operations -------------------------------------------------

    def insert(
        self,
        collection: str,
        doc_id: str,
        content: str,
        embedding: list[float],
        metadata: dict,
    ) -> int:
        self._store[collection]["docs"][doc_id] = {
            "id": doc_id,
            "content": content,
            "embedding": embedding,
            "metadata": metadata,
        }
        return len(self._store[collection]["docs"])

    def insert_batch(
        self,
        collection: str,
        ids: list[str],
        contents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> int:
        for doc_id, content, embedding, metadata in zip(ids, contents, embeddings, metadatas):
            self._store[collection]["docs"][doc_id] = {
                "id": doc_id,
                "content": content,
                "embedding": embedding,
                "metadata": metadata,
            }
        return len(ids)

    def search(
        self,
        collection: str,
        query_embedding: list[float],
        limit: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """Stub search: returns all docs with similarity=1.0 (no real vector math)."""
        docs = list(self._store.get(collection, {}).get("docs", {}).values())
        results = []
        for doc in docs[:limit]:
            results.append({
                "id": doc["id"],
                "content": doc["content"],
                "metadata": doc["metadata"],
                "similarity": 1.0,
            })
        return results

    def get(self, collection: str, doc_id: str) -> dict | None:
        doc = self._store.get(collection, {}).get("docs", {}).get(doc_id)
        if doc is None:
            return None
        return {"id": doc["id"], "content": doc["content"], "metadata": doc["metadata"]}

    def update(
        self,
        collection: str,
        doc_id: str,
        content: str,
        embedding: list[float],
        metadata: dict,
    ) -> bool:
        docs = self._store.get(collection, {}).get("docs", {})
        if doc_id not in docs:
            return False
        docs[doc_id] = {
            "id": doc_id,
            "content": content,
            "embedding": embedding,
            "metadata": metadata,
        }
        return True

    def delete(self, collection: str, doc_id: str) -> bool:
        docs = self._store.get(collection, {}).get("docs", {})
        if doc_id not in docs:
            return False
        del docs[doc_id]
        return True

    def collection_count(self, collection: str) -> int:
        return len(self._store.get(collection, {}).get("docs", {}))

    def collection_peek(self, collection: str, limit: int = 5) -> list[dict]:
        docs = list(self._store.get(collection, {}).get("docs", {}).values())
        return [
            {"id": d["id"], "content": d["content"], "metadata": d["metadata"]}
            for d in docs[:limit]
        ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def backend() -> _CompleteBackend:
    b = _CompleteBackend()
    b.connect()
    b.create_collection("test", dimension=4)
    return b


_EMBEDDING = [0.1, 0.2, 0.3, 0.4]
_METADATA = {"source": "unit-test"}


# ---------------------------------------------------------------------------
# Abstract class tests
# ---------------------------------------------------------------------------

class TestMemoryBackendAbstract:
    def test_cannot_instantiate_base_directly(self):
        """MemoryBackend is abstract and must not be instantiatable."""
        with pytest.raises(TypeError):
            MemoryBackend()  # type: ignore[abstract]

    def test_incomplete_subclass_raises_type_error(self):
        """A subclass missing abstract methods must raise TypeError on instantiation."""
        with pytest.raises(TypeError):
            _IncompleteBackend()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Concrete subclass tests
# ---------------------------------------------------------------------------

class TestCompleteMemoryBackend:

    # -- create_collection ---------------------------------------------------

    def test_create_collection_appears_in_list(self, backend):
        names = [c["name"] for c in backend.list_collections()]
        assert "test" in names

    def test_list_collections_returns_list_of_dicts(self, backend):
        result = backend.list_collections()
        assert isinstance(result, list)
        for item in result:
            assert "name" in item
            assert "count" in item

    # -- insert / get --------------------------------------------------------

    def test_insert_returns_new_count(self, backend):
        count = backend.insert("test", "doc1", "hello", _EMBEDDING, _METADATA)
        assert count == 1

    def test_insert_increments_count(self, backend):
        backend.insert("test", "doc1", "hello", _EMBEDDING, _METADATA)
        count = backend.insert("test", "doc2", "world", _EMBEDDING, _METADATA)
        assert count == 2

    def test_get_returns_correct_document(self, backend):
        backend.insert("test", "doc1", "hello world", _EMBEDDING, _METADATA)
        result = backend.get("test", "doc1")
        assert result is not None
        assert result["id"] == "doc1"
        assert result["content"] == "hello world"
        assert result["metadata"] == _METADATA

    def test_get_missing_doc_returns_none(self, backend):
        result = backend.get("test", "nonexistent")
        assert result is None

    # -- insert_batch --------------------------------------------------------

    def test_insert_batch_returns_count(self, backend):
        ids = ["a", "b", "c"]
        contents = ["doc a", "doc b", "doc c"]
        embeddings = [_EMBEDDING] * 3
        metadatas = [_METADATA] * 3
        count = backend.insert_batch("test", ids, contents, embeddings, metadatas)
        assert count == 3

    def test_insert_batch_docs_retrievable(self, backend):
        backend.insert_batch("test", ["x"], ["batch doc"], [_EMBEDDING], [_METADATA])
        result = backend.get("test", "x")
        assert result is not None
        assert result["content"] == "batch doc"

    # -- search --------------------------------------------------------------

    def test_search_returns_list(self, backend):
        backend.insert("test", "doc1", "hello", _EMBEDDING, _METADATA)
        results = backend.search("test", _EMBEDDING)
        assert isinstance(results, list)

    def test_search_result_has_required_keys(self, backend):
        backend.insert("test", "doc1", "hello", _EMBEDDING, _METADATA)
        results = backend.search("test", _EMBEDDING)
        assert len(results) > 0
        for result in results:
            assert "id" in result
            assert "content" in result
            assert "metadata" in result
            assert "similarity" in result

    def test_search_similarity_in_range(self, backend):
        backend.insert("test", "doc1", "hello", _EMBEDDING, _METADATA)
        results = backend.search("test", _EMBEDDING)
        for result in results:
            assert 0.0 <= result["similarity"] <= 1.0

    def test_search_respects_limit(self, backend):
        for i in range(5):
            backend.insert("test", f"doc{i}", f"content {i}", _EMBEDDING, _METADATA)
        results = backend.search("test", _EMBEDDING, limit=3)
        assert len(results) <= 3

    def test_search_empty_collection_returns_empty_list(self, backend):
        results = backend.search("test", _EMBEDDING)
        assert results == []

    # -- update --------------------------------------------------------------

    def test_update_existing_doc_returns_true(self, backend):
        backend.insert("test", "doc1", "original", _EMBEDDING, _METADATA)
        ok = backend.update("test", "doc1", "updated", _EMBEDDING, {"source": "updated"})
        assert ok is True

    def test_update_changes_content(self, backend):
        backend.insert("test", "doc1", "original", _EMBEDDING, _METADATA)
        backend.update("test", "doc1", "updated", _EMBEDDING, _METADATA)
        result = backend.get("test", "doc1")
        assert result["content"] == "updated"

    def test_update_missing_doc_returns_false(self, backend):
        ok = backend.update("test", "ghost", "content", _EMBEDDING, _METADATA)
        assert ok is False

    # -- delete --------------------------------------------------------------

    def test_delete_existing_doc_returns_true(self, backend):
        backend.insert("test", "doc1", "hello", _EMBEDDING, _METADATA)
        ok = backend.delete("test", "doc1")
        assert ok is True

    def test_delete_removes_document(self, backend):
        backend.insert("test", "doc1", "hello", _EMBEDDING, _METADATA)
        backend.delete("test", "doc1")
        assert backend.get("test", "doc1") is None

    def test_delete_missing_doc_returns_false(self, backend):
        ok = backend.delete("test", "nonexistent")
        assert ok is False

    # -- collection_count ----------------------------------------------------

    def test_collection_count_empty(self, backend):
        assert backend.collection_count("test") == 0

    def test_collection_count_after_inserts(self, backend):
        backend.insert("test", "doc1", "a", _EMBEDDING, _METADATA)
        backend.insert("test", "doc2", "b", _EMBEDDING, _METADATA)
        assert backend.collection_count("test") == 2

    def test_collection_count_after_delete(self, backend):
        backend.insert("test", "doc1", "a", _EMBEDDING, _METADATA)
        backend.delete("test", "doc1")
        assert backend.collection_count("test") == 0

    # -- collection_peek -----------------------------------------------------

    def test_collection_peek_returns_list(self, backend):
        result = backend.collection_peek("test")
        assert isinstance(result, list)

    def test_collection_peek_empty_collection(self, backend):
        assert backend.collection_peek("test") == []

    def test_collection_peek_respects_limit(self, backend):
        for i in range(10):
            backend.insert("test", f"doc{i}", f"content {i}", _EMBEDDING, _METADATA)
        result = backend.collection_peek("test", limit=3)
        assert len(result) <= 3

    def test_collection_peek_has_required_keys(self, backend):
        backend.insert("test", "doc1", "hello", _EMBEDDING, _METADATA)
        result = backend.collection_peek("test")
        assert len(result) > 0
        for item in result:
            assert "id" in item
            assert "content" in item
            assert "metadata" in item

    # -- delete_collection ---------------------------------------------------

    def test_delete_collection_returns_count(self, backend):
        backend.insert("test", "doc1", "a", _EMBEDDING, _METADATA)
        backend.insert("test", "doc2", "b", _EMBEDDING, _METADATA)
        count = backend.delete_collection("test")
        assert count == 2

    def test_delete_collection_nonexistent_returns_zero(self, backend):
        count = backend.delete_collection("no-such-collection")
        assert count == 0

    def test_delete_collection_removes_from_list(self, backend):
        backend.delete_collection("test")
        names = [c["name"] for c in backend.list_collections()]
        assert "test" not in names
