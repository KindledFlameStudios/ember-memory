"""Tests for LanceDB v2 backend.

All tests use tmp_path for fully isolated, in-process LanceDB instances —
no external server required.

Vectors are 4-dimensional for speed.
"""

import os

import pytest
from ember_memory.core.backends.lancedb_backend import LanceBackend


pytestmark = pytest.mark.skipif(
    os.getenv("EMBER_TEST_LANCEDB") != "1",
    reason=(
        "LanceDB is an optional backend; run with EMBER_TEST_LANCEDB=1 "
        "when validating the lancedb extra."
    ),
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def backend(tmp_path):
    """Return a connected LanceBackend with an isolated data directory."""
    b = LanceBackend(data_dir=str(tmp_path / "lance_db"))
    b.connect()
    return b


# ── Helpers ───────────────────────────────────────────────────────────────────


def _v(x=1.0, y=0.0, z=0.0, w=0.0) -> list[float]:
    """Return a 4-dimensional test vector."""
    return [x, y, z, w]


def _setup_collection(backend: LanceBackend, name: str = "test") -> None:
    backend.create_collection(name, dimension=4)


def _insert_one(
    backend: LanceBackend,
    collection: str = "test",
    doc_id: str = "doc1",
    content: str = "hello world",
    embedding: list[float] | None = None,
    metadata: dict | None = None,
) -> None:
    if embedding is None:
        embedding = _v(1.0)
    if metadata is None:
        metadata = {"tag": "greeting"}
    backend.insert(collection, doc_id, content, embedding, metadata)


# ── Interface compliance ───────────────────────────────────────────────────────


def test_implements_memory_backend_interface():
    from ember_memory.core.backends.base import MemoryBackend
    assert issubclass(LanceBackend, MemoryBackend)


def test_connect_required_before_use(tmp_path):
    """Calling any method before connect() must raise RuntimeError."""
    b = LanceBackend(data_dir=str(tmp_path / "no_connect"))
    with pytest.raises(RuntimeError, match="connect"):
        b.create_collection("test", dimension=4)


# ── Collection management ─────────────────────────────────────────────────────


def test_create_and_list_collection(backend):
    backend.create_collection("test", dimension=4)
    cols = backend.list_collections()
    names = [c["name"] for c in cols]
    assert "test" in names


def test_create_collection_is_idempotent(backend):
    """Calling create_collection twice should not raise."""
    backend.create_collection("test", dimension=4)
    backend.create_collection("test", dimension=4)  # should be a no-op
    cols = backend.list_collections()
    assert sum(1 for c in cols if c["name"] == "test") == 1


def test_list_collections_empty(backend):
    assert backend.list_collections() == []


def test_list_collections_count_reflects_inserts(backend):
    _setup_collection(backend)
    _insert_one(backend)
    cols = backend.list_collections()
    entry = next(c for c in cols if c["name"] == "test")
    assert entry["count"] == 1


def test_delete_collection_returns_count(backend):
    _setup_collection(backend)
    _insert_one(backend, doc_id="d1")
    _insert_one(backend, doc_id="d2", embedding=_v(0.0, 1.0))
    count = backend.delete_collection("test")
    assert count == 2


def test_delete_collection_removes_it(backend):
    _setup_collection(backend)
    backend.delete_collection("test")
    cols = backend.list_collections()
    assert not any(c["name"] == "test" for c in cols)


def test_delete_nonexistent_collection_returns_zero(backend):
    assert backend.delete_collection("does_not_exist") == 0


# ── Insert ────────────────────────────────────────────────────────────────────


def test_insert_returns_new_count(backend):
    _setup_collection(backend)
    count = backend.insert("test", "doc1", "hello", _v(1.0), {"x": "1"})
    assert count == 1
    count2 = backend.insert("test", "doc2", "world", _v(0.0, 1.0), {"x": "2"})
    assert count2 == 2


def test_insert_batch(backend):
    _setup_collection(backend)
    ids = ["a", "b", "c"]
    contents = ["alpha", "beta", "gamma"]
    embeddings = [_v(1.0), _v(0.0, 1.0), _v(0.0, 0.0, 1.0)]
    metadatas = [{"i": "0"}, {"i": "1"}, {"i": "2"}]
    inserted = backend.insert_batch("test", ids, contents, embeddings, metadatas)
    assert inserted == 3
    assert backend.collection_count("test") == 3


def test_insert_batch_empty_is_safe(backend):
    _setup_collection(backend)
    inserted = backend.insert_batch("test", [], [], [], [])
    assert inserted == 0


# ── Search ────────────────────────────────────────────────────────────────────


def test_insert_and_search(backend):
    _setup_collection(backend)
    _insert_one(backend)
    results = backend.search("test", query_embedding=_v(1.0), limit=1)
    assert len(results) == 1
    assert results[0]["id"] == "doc1"
    assert results[0]["content"] == "hello world"
    assert 0.0 <= results[0]["similarity"] <= 1.0


def test_search_returns_similarity_0_to_1(backend):
    """All similarity scores must be normalised to [0, 1]."""
    _setup_collection(backend)
    for i in range(4):
        vec = [0.0] * 4
        vec[i] = 1.0
        backend.insert("test", f"doc{i}", f"content {i}", vec, {"idx": str(i)})

    results = backend.search("test", query_embedding=_v(1.0, 0.0, 0.0, 0.0), limit=10)
    assert len(results) == 4
    for r in results:
        assert 0.0 <= r["similarity"] <= 1.0, f"Out-of-range similarity: {r['similarity']}"


def test_search_orders_by_descending_similarity(backend):
    """The most similar document should be ranked first."""
    _setup_collection(backend)
    backend.insert("test", "doc_exact", "exact match", _v(1.0, 0.0, 0.0, 0.0), {"k": "exact"})
    backend.insert("test", "doc_partial", "partial", _v(0.7, 0.7, 0.0, 0.0), {"k": "partial"})
    backend.insert("test", "doc_opposite", "opposite", _v(-1.0, 0.0, 0.0, 0.0), {"k": "opposite"})

    results = backend.search("test", query_embedding=_v(1.0, 0.0, 0.0, 0.0), limit=3)
    assert results[0]["id"] == "doc_exact"
    sims = [r["similarity"] for r in results]
    assert sims == sorted(sims, reverse=True)


def test_search_empty_collection_returns_empty(backend):
    _setup_collection(backend)
    results = backend.search("test", query_embedding=_v(1.0), limit=5)
    assert results == []


def test_search_respects_limit(backend):
    _setup_collection(backend)
    for i in range(5):
        vec = [0.0] * 4
        vec[i % 4] = 1.0
        backend.insert("test", f"doc{i}", f"content {i}", vec, {"i": str(i)})
    results = backend.search("test", query_embedding=_v(1.0), limit=2)
    assert len(results) <= 2


def test_search_with_metadata_filter(backend):
    """Metadata filter should restrict results to matching documents."""
    _setup_collection(backend)
    backend.insert("test", "a", "content a", _v(1.0), {"tag": "alpha"})
    backend.insert("test", "b", "content b", _v(0.9, 0.1), {"tag": "beta"})

    results = backend.search("test", query_embedding=_v(1.0), limit=10, filters={"tag": "alpha"})
    assert all(r["metadata"]["tag"] == "alpha" for r in results)


# ── Get ───────────────────────────────────────────────────────────────────────


def test_insert_and_get_by_id(backend):
    _setup_collection(backend)
    _insert_one(backend, doc_id="doc1", content="hello world", metadata={"tag": "greeting"})
    result = backend.get("test", "doc1")
    assert result is not None
    assert result["id"] == "doc1"
    assert result["content"] == "hello world"
    assert result["metadata"]["tag"] == "greeting"


def test_get_nonexistent_returns_none(backend):
    _setup_collection(backend)
    assert backend.get("test", "ghost") is None


# ── Update ────────────────────────────────────────────────────────────────────


def test_update_document(backend):
    _setup_collection(backend)
    _insert_one(backend, doc_id="doc1", content="original", metadata={"v": 1})
    updated = backend.update("test", "doc1", "updated content", _v(0.0, 1.0), {"v": 2})
    assert updated is True
    doc = backend.get("test", "doc1")
    assert doc["content"] == "updated content"
    assert doc["metadata"]["v"] == 2


def test_update_nonexistent_returns_false(backend):
    _setup_collection(backend)
    result = backend.update("test", "ghost", "content", _v(1.0), {})
    assert result is False


def test_update_does_not_change_count(backend):
    _setup_collection(backend)
    _insert_one(backend)
    count_before = backend.collection_count("test")
    backend.update("test", "doc1", "new content", _v(0.0, 1.0), {"v": "updated"})
    count_after = backend.collection_count("test")
    assert count_before == count_after


# ── Delete ────────────────────────────────────────────────────────────────────


def test_delete_document(backend):
    _setup_collection(backend)
    _insert_one(backend)
    deleted = backend.delete("test", "doc1")
    assert deleted is True
    assert backend.get("test", "doc1") is None


def test_delete_nonexistent_returns_false(backend):
    _setup_collection(backend)
    assert backend.delete("test", "ghost") is False


def test_delete_reduces_count(backend):
    _setup_collection(backend)
    _insert_one(backend, doc_id="d1")
    _insert_one(backend, doc_id="d2", embedding=_v(0.0, 1.0))
    backend.delete("test", "d1")
    assert backend.collection_count("test") == 1


# ── collection_count ──────────────────────────────────────────────────────────


def test_collection_count(backend):
    _setup_collection(backend)
    assert backend.collection_count("test") == 0
    _insert_one(backend)
    assert backend.collection_count("test") == 1


def test_collection_count_nonexistent_returns_zero(backend):
    assert backend.collection_count("does_not_exist") == 0


# ── collection_peek ───────────────────────────────────────────────────────────


def test_collection_peek(backend):
    _setup_collection(backend)
    _insert_one(backend, doc_id="p1", content="peek content")
    results = backend.collection_peek("test", limit=5)
    assert len(results) == 1
    assert results[0]["id"] == "p1"
    assert results[0]["content"] == "peek content"
    assert "metadata" in results[0]


def test_collection_peek_respects_limit(backend):
    _setup_collection(backend)
    for i in range(5):
        vec = [0.0] * 4
        vec[i % 4] = 1.0
        backend.insert("test", f"doc{i}", f"content {i}", vec, {"i": str(i)})
    results = backend.collection_peek("test", limit=3)
    assert len(results) <= 3


def test_collection_peek_empty_collection(backend):
    _setup_collection(backend)
    assert backend.collection_peek("test") == []


def test_collection_peek_nonexistent_collection(backend):
    assert backend.collection_peek("no_such_collection") == []
