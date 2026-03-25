"""Tests for the Pinecone v2 backend.

All tests mock the pinecone client — no cloud account or API key required.
The mocks validate that PineconeBackend calls the correct client methods with
the correct arguments and that the interface contract is upheld.

Skip the entire module gracefully if pinecone is not installed.
"""

from unittest.mock import MagicMock, patch, call

import pytest

try:
    import pinecone
    HAS_PINECONE = True
except ImportError:
    HAS_PINECONE = False

pytestmark = pytest.mark.skipif(not HAS_PINECONE, reason="pinecone not installed")

from ember_memory.core.backends.pinecone_backend import (  # noqa: E402
    PineconeBackend,
    _COLLECTIONS_META_NAMESPACE,
    _COLLECTION_META_DOC_PREFIX,
)


# ── Helper factories ──────────────────────────────────────────────────────────


def _make_backend(
    api_key: str = "test-key",
    index_name: str = "test-index",
) -> PineconeBackend:
    return PineconeBackend(api_key=api_key, index_name=index_name)


def _v(*args: float) -> list[float]:
    """4-dimensional test vector."""
    base = list(args) + [0.0] * 4
    return base[:4]


def _make_pc_and_index() -> tuple[MagicMock, MagicMock]:
    """Return (mock_pc, mock_index) with sane defaults wired up."""
    mock_index = MagicMock()
    mock_pc = MagicMock()
    mock_pc.has_index.return_value = True
    mock_pc.Index.return_value = mock_index

    # describe_index_stats defaults — returns no namespaces, dimension 4.
    stats = MagicMock()
    stats.dimension = 4
    stats.namespaces = {}
    mock_index.describe_index_stats.return_value = stats

    # Default fetch returns empty.
    empty_fetch = MagicMock()
    empty_fetch.vectors = {}
    mock_index.fetch.return_value = empty_fetch

    # Default list returns nothing.
    mock_index.list.return_value = iter([])

    # Default query returns no matches.
    query_resp = MagicMock()
    query_resp.matches = []
    mock_index.query.return_value = query_resp

    return mock_pc, mock_index


def _connected_backend(mock_pc: MagicMock, index_name: str = "test-index") -> PineconeBackend:
    """Build and connect a backend with the given mock Pinecone client."""
    backend = _make_backend(index_name=index_name)
    with patch("pinecone.Pinecone", return_value=mock_pc):
        backend.connect()
    return backend


# ── Interface compliance ───────────────────────────────────────────────────────


def test_implements_memory_backend_interface():
    from ember_memory.core.backends.base import MemoryBackend
    assert issubclass(PineconeBackend, MemoryBackend)


# ── connect() ────────────────────────────────────────────────────────────────


def test_connect_initialises_client_and_index():
    """connect() should create a Pinecone client and call Index(name=...)."""
    mock_pc, mock_index = _make_pc_and_index()
    backend = _make_backend(index_name="my-index")
    with patch("pinecone.Pinecone", return_value=mock_pc) as mock_cls:
        backend.connect()
        mock_cls.assert_called_once_with(api_key="test-key")
    mock_pc.has_index.assert_called_once_with("my-index")
    mock_pc.Index.assert_called_once_with(name="my-index")
    assert backend._index is mock_index


def test_connect_creates_index_when_absent():
    """connect() should call create_index when the index does not exist."""
    mock_pc, _mock_index = _make_pc_and_index()
    mock_pc.has_index.return_value = False
    backend = _make_backend(index_name="ember-memory")
    with patch("pinecone.Pinecone", return_value=mock_pc):
        with patch("pinecone.ServerlessSpec") as mock_spec:
            mock_spec.return_value = "spec-obj"
            backend.connect()
    mock_pc.create_index.assert_called_once()
    call_kwargs = mock_pc.create_index.call_args.kwargs
    assert call_kwargs["name"] == "ember-memory"
    assert call_kwargs["metric"] == "cosine"


def test_connect_skips_create_when_index_exists():
    """connect() should not call create_index when the index already exists."""
    mock_pc, _ = _make_pc_and_index()
    mock_pc.has_index.return_value = True
    backend = _make_backend()
    with patch("pinecone.Pinecone", return_value=mock_pc):
        backend.connect()
    mock_pc.create_index.assert_not_called()


def test_require_index_raises_before_connect():
    """Any method before connect() should raise RuntimeError."""
    backend = _make_backend()
    with pytest.raises(RuntimeError, match="connect"):
        backend.create_collection("test", dimension=4)


def test_connect_raises_if_pinecone_not_installed():
    """connect() raises RuntimeError when the pinecone package is missing."""
    backend = _make_backend()
    with patch.dict("sys.modules", {"pinecone": None}):
        with pytest.raises(RuntimeError, match="pinecone package is not installed"):
            backend.connect()


# ── create_collection() ───────────────────────────────────────────────────────


def test_create_collection_upserts_metadata_placeholder():
    """create_collection() should upsert a registration record into the meta namespace."""
    mock_pc, mock_index = _make_pc_and_index()
    backend = _connected_backend(mock_pc)
    backend.create_collection("articles", dimension=4, description="Test collection")

    mock_index.upsert.assert_called_once()
    call_kwargs = mock_index.upsert.call_args.kwargs
    assert call_kwargs["namespace"] == _COLLECTIONS_META_NAMESPACE
    vectors = call_kwargs["vectors"]
    assert len(vectors) == 1
    vec = vectors[0]
    assert vec["id"] == f"{_COLLECTION_META_DOC_PREFIX}articles"
    assert vec["metadata"]["ember_collection_name"] == "articles"
    assert vec["metadata"]["ember_dimension"] == 4
    assert vec["metadata"]["ember_description"] == "Test collection"


def test_create_collection_skips_if_already_registered():
    """create_collection() should be idempotent — no upsert if already registered."""
    mock_pc, mock_index = _make_pc_and_index()

    # Simulate existing registration.
    meta_id = f"{_COLLECTION_META_DOC_PREFIX}articles"
    fetch_result = MagicMock()
    fetch_result.vectors = {meta_id: MagicMock()}
    mock_index.fetch.return_value = fetch_result

    backend = _connected_backend(mock_pc)
    backend.create_collection("articles", dimension=4)

    mock_index.upsert.assert_not_called()


def test_create_collection_without_description():
    """create_collection() without description should not include ember_description."""
    mock_pc, mock_index = _make_pc_and_index()
    backend = _connected_backend(mock_pc)
    backend.create_collection("notes", dimension=128)

    call_kwargs = mock_index.upsert.call_args.kwargs
    vec_meta = call_kwargs["vectors"][0]["metadata"]
    assert "ember_description" not in vec_meta


# ── delete_collection() ───────────────────────────────────────────────────────


def test_delete_collection_deletes_namespace_and_meta():
    """delete_collection() should delete all vectors and the meta registration."""
    mock_pc, mock_index = _make_pc_and_index()

    # Simulate a namespace with 3 vectors.
    stats = MagicMock()
    stats.dimension = 4
    stats.namespaces = {"articles": MagicMock(vector_count=3)}
    mock_index.describe_index_stats.return_value = stats

    backend = _connected_backend(mock_pc)
    count = backend.delete_collection("articles")

    assert count == 3
    # Should have called delete twice: once for namespace, once for meta entry.
    assert mock_index.delete.call_count == 2
    calls = mock_index.delete.call_args_list
    namespaces_called = {c.kwargs.get("namespace") for c in calls}
    assert "articles" in namespaces_called
    assert _COLLECTIONS_META_NAMESPACE in namespaces_called


def test_delete_collection_returns_zero_when_not_found():
    """delete_collection() on a missing namespace should return 0."""
    mock_pc, mock_index = _make_pc_and_index()
    # Stats show no namespaces.
    stats = MagicMock()
    stats.dimension = 4
    stats.namespaces = {}
    mock_index.describe_index_stats.return_value = stats

    backend = _connected_backend(mock_pc)
    count = backend.delete_collection("nonexistent")

    assert count == 0


# ── list_collections() ────────────────────────────────────────────────────────


def test_list_collections_returns_registered_collections():
    """list_collections() should return dicts with name, count, dimension."""
    mock_pc, mock_index = _make_pc_and_index()

    # Live stats show one namespace.
    stats = MagicMock()
    stats.dimension = 4
    stats.namespaces = {"articles": MagicMock(vector_count=5)}
    mock_index.describe_index_stats.return_value = stats

    # list() returns one metadata id.
    meta_id = f"{_COLLECTION_META_DOC_PREFIX}articles"
    mock_index.list.return_value = iter([[meta_id]])

    # fetch() returns the metadata vector.
    meta_vec = MagicMock()
    meta_vec.metadata = {
        "ember_collection_name": "articles",
        "ember_dimension": 4,
    }
    fetch_result = MagicMock()
    fetch_result.vectors = {meta_id: meta_vec}
    mock_index.fetch.return_value = fetch_result

    backend = _connected_backend(mock_pc)
    result = backend.list_collections()

    assert len(result) == 1
    assert result[0]["name"] == "articles"
    assert result[0]["count"] == 5
    assert result[0]["dimension"] == 4


def test_list_collections_includes_description():
    """list_collections() should include description when stored in metadata."""
    mock_pc, mock_index = _make_pc_and_index()

    stats = MagicMock()
    stats.dimension = 4
    stats.namespaces = {"notes": MagicMock(vector_count=0)}
    mock_index.describe_index_stats.return_value = stats

    meta_id = f"{_COLLECTION_META_DOC_PREFIX}notes"
    mock_index.list.return_value = iter([[meta_id]])

    meta_vec = MagicMock()
    meta_vec.metadata = {
        "ember_collection_name": "notes",
        "ember_dimension": 4,
        "ember_description": "My notes",
    }
    fetch_result = MagicMock()
    fetch_result.vectors = {meta_id: meta_vec}
    mock_index.fetch.return_value = fetch_result

    backend = _connected_backend(mock_pc)
    result = backend.list_collections()

    assert result[0].get("description") == "My notes"


def test_list_collections_empty_when_no_registrations():
    """list_collections() returns [] when no collections have been registered."""
    mock_pc, mock_index = _make_pc_and_index()
    # Empty list.
    mock_index.list.return_value = iter([[]])
    fetch_result = MagicMock()
    fetch_result.vectors = {}
    mock_index.fetch.return_value = fetch_result

    backend = _connected_backend(mock_pc)
    result = backend.list_collections()

    assert result == []


# ── insert() ─────────────────────────────────────────────────────────────────


def test_insert_upserts_vector_with_content_in_metadata():
    """insert() should call index.upsert with content stored in metadata."""
    mock_pc, mock_index = _make_pc_and_index()

    # Simulate post-insert count of 1.
    stats_after = MagicMock()
    stats_after.dimension = 4
    stats_after.namespaces = {"docs": MagicMock(vector_count=1)}
    mock_index.describe_index_stats.return_value = stats_after

    backend = _connected_backend(mock_pc)
    count = backend.insert("docs", "doc-1", "Hello world", _v(1.0), {"tag": "test"})

    mock_index.upsert.assert_called_once()
    call_kwargs = mock_index.upsert.call_args.kwargs
    assert call_kwargs["namespace"] == "docs"
    vectors = call_kwargs["vectors"]
    assert len(vectors) == 1
    vec = vectors[0]
    assert vec["id"] == "doc-1"
    assert vec["values"] == _v(1.0)
    assert vec["metadata"]["_content"] == "Hello world"
    assert vec["metadata"]["_doc_id"] == "doc-1"
    assert vec["metadata"]["tag"] == "test"
    assert count == 1


def test_insert_returns_new_count():
    """insert() should return the post-insert collection count."""
    mock_pc, mock_index = _make_pc_and_index()
    stats = MagicMock()
    stats.dimension = 4
    stats.namespaces = {"col": MagicMock(vector_count=7)}
    mock_index.describe_index_stats.return_value = stats

    backend = _connected_backend(mock_pc)
    count = backend.insert("col", "d1", "text", _v(0.5), {})

    assert count == 7


# ── insert_batch() ────────────────────────────────────────────────────────────


def test_insert_batch_upserts_all_vectors():
    """insert_batch() should upsert all vectors in a single call."""
    mock_pc, mock_index = _make_pc_and_index()
    backend = _connected_backend(mock_pc)

    ids = ["a", "b", "c"]
    contents = ["alpha", "beta", "gamma"]
    embeddings = [_v(1.0), _v(0.0, 1.0), _v(0.0, 0.0, 1.0)]
    metadatas = [{"i": "0"}, {"i": "1"}, {"i": "2"}]

    result = backend.insert_batch("col", ids, contents, embeddings, metadatas)

    mock_index.upsert.assert_called_once()
    call_kwargs = mock_index.upsert.call_args.kwargs
    assert call_kwargs["namespace"] == "col"
    assert len(call_kwargs["vectors"]) == 3
    assert result == 3


def test_insert_batch_correct_metadata_per_vector():
    """insert_batch() should store each document's content in its own metadata."""
    mock_pc, mock_index = _make_pc_and_index()
    backend = _connected_backend(mock_pc)

    backend.insert_batch(
        "col",
        ["x", "y"],
        ["content x", "content y"],
        [_v(1.0), _v(0.0, 1.0)],
        [{"k": "1"}, {"k": "2"}],
    )

    vectors = mock_index.upsert.call_args.kwargs["vectors"]
    assert vectors[0]["metadata"]["_content"] == "content x"
    assert vectors[1]["metadata"]["_content"] == "content y"


def test_insert_batch_empty_returns_zero():
    """insert_batch() with empty lists should not call upsert and return 0."""
    mock_pc, mock_index = _make_pc_and_index()
    backend = _connected_backend(mock_pc)

    result = backend.insert_batch("col", [], [], [], [])

    mock_index.upsert.assert_not_called()
    assert result == 0


# ── search() ─────────────────────────────────────────────────────────────────


def _make_match(doc_id: str, content: str, metadata: dict, score: float) -> MagicMock:
    """Build a mock Pinecone query match object."""
    match = MagicMock()
    match.id = doc_id
    match.score = score
    match.metadata = {"_content": content, "_doc_id": doc_id, **metadata}
    return match


def test_search_calls_query_with_correct_args():
    """search() should call index.query with vector, top_k, namespace."""
    mock_pc, mock_index = _make_pc_and_index()
    backend = _connected_backend(mock_pc)

    backend.search("articles", _v(1.0), limit=5)

    mock_index.query.assert_called_once()
    call_kwargs = mock_index.query.call_args.kwargs
    assert call_kwargs["vector"] == _v(1.0)
    assert call_kwargs["top_k"] == 5
    assert call_kwargs["namespace"] == "articles"
    assert call_kwargs["include_metadata"] is True


def test_search_returns_correct_structure():
    """search() results must have id, content, metadata, similarity keys."""
    mock_pc, mock_index = _make_pc_and_index()

    query_resp = MagicMock()
    query_resp.matches = [
        _make_match("doc-42", "hello world", {"source": "test"}, 0.88),
    ]
    mock_index.query.return_value = query_resp

    backend = _connected_backend(mock_pc)
    results = backend.search("docs", _v(1.0))

    assert len(results) == 1
    r = results[0]
    assert r["id"] == "doc-42"
    assert r["content"] == "hello world"
    assert r["metadata"] == {"source": "test"}
    assert r["similarity"] == pytest.approx(0.88)


def test_search_does_not_leak_internal_metadata_keys():
    """search() must strip _content and _doc_id from the returned metadata."""
    mock_pc, mock_index = _make_pc_and_index()

    query_resp = MagicMock()
    query_resp.matches = [_make_match("d1", "text", {"tag": "x"}, 0.9)]
    mock_index.query.return_value = query_resp

    backend = _connected_backend(mock_pc)
    results = backend.search("col", _v(1.0))

    meta = results[0]["metadata"]
    assert "_content" not in meta
    assert "_doc_id" not in meta
    assert "tag" in meta


def test_search_similarity_in_0_to_1():
    """Pinecone cosine scores are already in [0, 1] — pass them through unchanged."""
    mock_pc, mock_index = _make_pc_and_index()

    query_resp = MagicMock()
    query_resp.matches = [
        _make_match("d1", "t", {}, 1.0),
        _make_match("d2", "t", {}, 0.5),
        _make_match("d3", "t", {}, 0.0),
    ]
    mock_index.query.return_value = query_resp

    backend = _connected_backend(mock_pc)
    results = backend.search("col", _v(1.0))

    for r in results:
        assert 0.0 <= r["similarity"] <= 1.0, f"Out of range: {r['similarity']}"


def test_search_with_filter_builds_pinecone_filter():
    """search() with filters should pass a filter dict to index.query."""
    mock_pc, mock_index = _make_pc_and_index()
    backend = _connected_backend(mock_pc)

    backend.search("col", _v(1.0), filters={"tag": "alpha"})

    call_kwargs = mock_index.query.call_args.kwargs
    assert "filter" in call_kwargs
    assert call_kwargs["filter"] == {"tag": {"$eq": "alpha"}}


def test_search_with_multiple_filters_uses_and():
    """search() with multiple filters should use $and."""
    mock_pc, mock_index = _make_pc_and_index()
    backend = _connected_backend(mock_pc)

    backend.search("col", _v(1.0), filters={"tag": "alpha", "source": "web"})

    call_kwargs = mock_index.query.call_args.kwargs
    assert "filter" in call_kwargs
    pinecone_filter = call_kwargs["filter"]
    assert "$and" in pinecone_filter
    assert len(pinecone_filter["$and"]) == 2


def test_search_returns_empty_on_exception():
    """search() should return [] rather than raising on a query error."""
    mock_pc, mock_index = _make_pc_and_index()
    mock_index.query.side_effect = Exception("network error")

    backend = _connected_backend(mock_pc)
    results = backend.search("col", _v(1.0))

    assert results == []


# ── get() ─────────────────────────────────────────────────────────────────────


def test_get_fetches_by_id_and_returns_doc():
    """get() should call index.fetch and return id, content, metadata."""
    mock_pc, mock_index = _make_pc_and_index()

    vec = MagicMock()
    vec.metadata = {"_content": "some text", "_doc_id": "doc-5", "x": 1}
    fetch_result = MagicMock()
    fetch_result.vectors = {"doc-5": vec}
    mock_index.fetch.return_value = fetch_result

    backend = _connected_backend(mock_pc)
    result = backend.get("articles", "doc-5")

    mock_index.fetch.assert_called_with(ids=["doc-5"], namespace="articles")
    assert result is not None
    assert result["id"] == "doc-5"
    assert result["content"] == "some text"
    assert result["metadata"] == {"x": 1}


def test_get_returns_none_when_not_found():
    """get() should return None when the document does not exist."""
    mock_pc, mock_index = _make_pc_and_index()
    fetch_result = MagicMock()
    fetch_result.vectors = {}
    mock_index.fetch.return_value = fetch_result

    backend = _connected_backend(mock_pc)
    result = backend.get("articles", "ghost-id")

    assert result is None


def test_get_returns_none_on_exception():
    """get() should return None if index.fetch raises."""
    mock_pc, mock_index = _make_pc_and_index()
    mock_index.fetch.side_effect = Exception("timeout")

    backend = _connected_backend(mock_pc)
    result = backend.get("articles", "doc-99")

    assert result is None


def test_get_does_not_leak_internal_metadata():
    """get() must strip _content and _doc_id from the returned metadata."""
    mock_pc, mock_index = _make_pc_and_index()

    vec = MagicMock()
    vec.metadata = {"_content": "text", "_doc_id": "id1", "keep": "this"}
    fetch_result = MagicMock()
    fetch_result.vectors = {"id1": vec}
    mock_index.fetch.return_value = fetch_result

    backend = _connected_backend(mock_pc)
    result = backend.get("col", "id1")

    assert "_content" not in result["metadata"]
    assert "_doc_id" not in result["metadata"]
    assert result["metadata"]["keep"] == "this"


# ── update() ─────────────────────────────────────────────────────────────────


def test_update_upserts_when_document_exists():
    """update() should call index.upsert when the document exists."""
    mock_pc, mock_index = _make_pc_and_index()

    vec = MagicMock()
    vec.metadata = {"_content": "old", "_doc_id": "doc-1"}
    fetch_result = MagicMock()
    fetch_result.vectors = {"doc-1": vec}
    mock_index.fetch.return_value = fetch_result

    backend = _connected_backend(mock_pc)
    result = backend.update("docs", "doc-1", "new content", _v(0.5, 0.5), {"v": 2})

    assert result is True
    mock_index.upsert.assert_called_once()
    call_kwargs = mock_index.upsert.call_args.kwargs
    assert call_kwargs["namespace"] == "docs"
    upserted_vec = call_kwargs["vectors"][0]
    assert upserted_vec["metadata"]["_content"] == "new content"
    assert upserted_vec["metadata"]["v"] == 2


def test_update_returns_false_when_not_found():
    """update() should return False and not call upsert when doc is missing."""
    mock_pc, mock_index = _make_pc_and_index()
    fetch_result = MagicMock()
    fetch_result.vectors = {}
    mock_index.fetch.return_value = fetch_result

    backend = _connected_backend(mock_pc)
    result = backend.update("docs", "ghost", "text", _v(1.0), {})

    assert result is False
    mock_index.upsert.assert_not_called()


# ── delete() ─────────────────────────────────────────────────────────────────


def test_delete_calls_delete_when_document_exists():
    """delete() should call index.delete when the document exists."""
    mock_pc, mock_index = _make_pc_and_index()

    vec = MagicMock()
    fetch_result = MagicMock()
    fetch_result.vectors = {"doc-1": vec}
    mock_index.fetch.return_value = fetch_result

    backend = _connected_backend(mock_pc)
    result = backend.delete("docs", "doc-1")

    assert result is True
    mock_index.delete.assert_called_once_with(ids=["doc-1"], namespace="docs")


def test_delete_returns_false_when_not_found():
    """delete() should return False and not call index.delete when missing."""
    mock_pc, mock_index = _make_pc_and_index()
    fetch_result = MagicMock()
    fetch_result.vectors = {}
    mock_index.fetch.return_value = fetch_result

    backend = _connected_backend(mock_pc)
    result = backend.delete("docs", "ghost-id")

    assert result is False
    mock_index.delete.assert_not_called()


# ── collection_count() ────────────────────────────────────────────────────────


def test_collection_count_returns_vector_count_from_stats():
    """collection_count() should read vector_count from describe_index_stats."""
    mock_pc, mock_index = _make_pc_and_index()
    stats = MagicMock()
    stats.dimension = 4
    stats.namespaces = {"articles": MagicMock(vector_count=42)}
    mock_index.describe_index_stats.return_value = stats

    backend = _connected_backend(mock_pc)
    count = backend.collection_count("articles")

    assert count == 42


def test_collection_count_returns_zero_for_missing_namespace():
    """collection_count() returns 0 when the namespace is absent from stats."""
    mock_pc, mock_index = _make_pc_and_index()
    stats = MagicMock()
    stats.dimension = 4
    stats.namespaces = {}
    mock_index.describe_index_stats.return_value = stats

    backend = _connected_backend(mock_pc)
    count = backend.collection_count("nonexistent")

    assert count == 0


def test_collection_count_returns_zero_on_exception():
    """collection_count() returns 0 when describe_index_stats raises."""
    mock_pc, mock_index = _make_pc_and_index()
    mock_index.describe_index_stats.side_effect = Exception("API error")

    backend = _connected_backend(mock_pc)
    count = backend.collection_count("col")

    assert count == 0


# ── collection_peek() ─────────────────────────────────────────────────────────


def test_collection_peek_returns_documents():
    """collection_peek() should return docs with id, content, metadata."""
    mock_pc, mock_index = _make_pc_and_index()

    mock_index.list.return_value = iter([["doc-1", "doc-2"]])

    vec1 = MagicMock()
    vec1.metadata = {"_content": "first doc", "_doc_id": "doc-1", "k": "v"}
    vec2 = MagicMock()
    vec2.metadata = {"_content": "second doc", "_doc_id": "doc-2"}
    fetch_result = MagicMock()
    fetch_result.vectors = {"doc-1": vec1, "doc-2": vec2}
    mock_index.fetch.return_value = fetch_result

    backend = _connected_backend(mock_pc)
    result = backend.collection_peek("articles", limit=5)

    mock_index.list.assert_called_once_with(namespace="articles")
    assert len(result) == 2
    assert result[0]["id"] == "doc-1"
    assert result[0]["content"] == "first doc"
    assert result[0]["metadata"] == {"k": "v"}


def test_collection_peek_respects_limit():
    """collection_peek() should not return more than limit documents."""
    mock_pc, mock_index = _make_pc_and_index()

    # list returns 10 IDs but limit is 3.
    ids = [f"doc-{i}" for i in range(10)]
    mock_index.list.return_value = iter([ids])

    fetch_result = MagicMock()
    fetch_result.vectors = {
        doc_id: MagicMock(metadata={"_content": f"c{doc_id}", "_doc_id": doc_id})
        for doc_id in ids[:3]
    }
    mock_index.fetch.return_value = fetch_result

    backend = _connected_backend(mock_pc)
    result = backend.collection_peek("col", limit=3)

    # Fetch should have been called with at most 3 IDs.
    fetched_ids = mock_index.fetch.call_args.kwargs["ids"]
    assert len(fetched_ids) <= 3
    assert len(result) <= 3


def test_collection_peek_returns_empty_when_list_fails():
    """collection_peek() returns [] when index.list raises."""
    mock_pc, mock_index = _make_pc_and_index()
    mock_index.list.side_effect = Exception("namespace not found")

    backend = _connected_backend(mock_pc)
    result = backend.collection_peek("empty_col")

    assert result == []


def test_collection_peek_strips_internal_metadata():
    """collection_peek() must not expose _content or _doc_id in metadata."""
    mock_pc, mock_index = _make_pc_and_index()
    mock_index.list.return_value = iter([["id1"]])

    vec = MagicMock()
    vec.metadata = {"_content": "text", "_doc_id": "id1", "keep": "yes"}
    fetch_result = MagicMock()
    fetch_result.vectors = {"id1": vec}
    mock_index.fetch.return_value = fetch_result

    backend = _connected_backend(mock_pc)
    result = backend.collection_peek("col")

    meta = result[0]["metadata"]
    assert "_content" not in meta
    assert "_doc_id" not in meta
    assert meta["keep"] == "yes"


# ── Namespace isolation ────────────────────────────────────────────────────────


def test_insert_uses_correct_namespace():
    """insert() must pass the collection name as the namespace to upsert."""
    mock_pc, mock_index = _make_pc_and_index()
    backend = _connected_backend(mock_pc)

    backend.insert("my-namespace", "d1", "text", _v(1.0), {})

    call_kwargs = mock_index.upsert.call_args.kwargs
    assert call_kwargs["namespace"] == "my-namespace"


def test_search_uses_correct_namespace():
    """search() must pass the collection name as the namespace to query."""
    mock_pc, mock_index = _make_pc_and_index()
    backend = _connected_backend(mock_pc)

    backend.search("my-namespace", _v(1.0))

    call_kwargs = mock_index.query.call_args.kwargs
    assert call_kwargs["namespace"] == "my-namespace"


def test_delete_collection_deletes_correct_namespace():
    """delete_collection() must delete vectors in the correct namespace only."""
    mock_pc, mock_index = _make_pc_and_index()
    stats = MagicMock()
    stats.dimension = 4
    stats.namespaces = {"target": MagicMock(vector_count=2)}
    mock_index.describe_index_stats.return_value = stats

    backend = _connected_backend(mock_pc)
    backend.delete_collection("target")

    delete_calls = mock_index.delete.call_args_list
    namespaces_deleted = [c.kwargs.get("namespace") for c in delete_calls]
    assert "target" in namespaces_deleted
