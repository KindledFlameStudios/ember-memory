"""Tests for the Weaviate v2 backend.

All tests mock the weaviate-client — no running Weaviate server is required.
The mocks validate that WeaviateBackend calls the correct client methods with
the correct arguments.

Skip the entire module gracefully if weaviate-client is not installed.
"""

import json
import uuid
from unittest.mock import MagicMock, patch, call

import pytest

pytest.importorskip("weaviate")

from ember_memory.core.backends.weaviate_backend import (  # noqa: E402
    WeaviateBackend,
    _class_name,
    _doc_uuid,
    _UUID_NAMESPACE,
)


# ── Helper factories ──────────────────────────────────────────────────────────


def _make_backend(url: str = "http://localhost:8080", api_key: str | None = None) -> WeaviateBackend:
    return WeaviateBackend(url=url, api_key=api_key)


def _mock_client() -> MagicMock:
    """Return a MagicMock that looks enough like a WeaviateClient."""
    client = MagicMock()
    client.is_ready.return_value = True
    return client


def _v(*args: float) -> list[float]:
    """Convenience: 4-dim test vector."""
    base = list(args) + [0.0] * 4
    return base[:4]


# ── Utility helpers ───────────────────────────────────────────────────────────


def test_class_name_capitalises():
    assert _class_name("my-collection") == "My_collection"


def test_class_name_replaces_hyphens():
    assert _class_name("some-long-name") == "Some_long_name"


def test_class_name_already_valid():
    assert _class_name("Articles") == "Articles"


def test_doc_uuid_is_deterministic():
    u1 = _doc_uuid("doc-42")
    u2 = _doc_uuid("doc-42")
    assert u1 == u2


def test_doc_uuid_differs_for_different_ids():
    assert _doc_uuid("doc-1") != _doc_uuid("doc-2")


def test_doc_uuid_is_valid_uuid():
    u = _doc_uuid("some-id")
    # Should not raise
    uuid.UUID(u)


# ── Interface compliance ───────────────────────────────────────────────────────


def test_implements_memory_backend_interface():
    from ember_memory.core.backends.base import MemoryBackend
    assert issubclass(WeaviateBackend, MemoryBackend)


# ── connect() ────────────────────────────────────────────────────────────────


def test_connect_local_creates_client():
    """connect() without api_key should call connect_to_local."""
    mock_client = _mock_client()
    with patch("weaviate.connect_to_local", return_value=mock_client) as mock_connect:
        backend = _make_backend(url="http://localhost:8080")
        backend.connect()
        mock_connect.assert_called_once()
        assert backend._client is mock_client


def test_connect_cloud_uses_api_key():
    """connect() with api_key should call connect_to_weaviate_cloud."""
    mock_client = _mock_client()
    with patch("weaviate.connect_to_weaviate_cloud", return_value=mock_client) as mock_connect:
        with patch("weaviate.classes.init.Auth.api_key") as mock_auth:
            mock_auth.return_value = "auth-token"
            backend = _make_backend(url="https://my.weaviate.cloud", api_key="secret")
            backend.connect()
            mock_connect.assert_called_once()
            mock_auth.assert_called_once_with("secret")


def test_connect_raises_if_server_not_ready():
    """connect() raises RuntimeError when is_ready() returns False."""
    mock_client = _mock_client()
    mock_client.is_ready.return_value = False
    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        with pytest.raises(RuntimeError, match="not ready"):
            backend.connect()
        assert backend._client is None


def test_require_client_raises_before_connect():
    """Any method before connect() should raise RuntimeError."""
    backend = _make_backend()
    with pytest.raises(RuntimeError, match="connect"):
        backend.create_collection("test", dimension=4)


# ── create_collection() ───────────────────────────────────────────────────────


def test_create_collection_calls_collections_create():
    """create_collection() should call client.collections.create with correct params."""
    mock_client = _mock_client()
    mock_client.collections.exists.return_value = False

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        backend.create_collection("my-docs", dimension=384, description="Test collection")

    mock_client.collections.exists.assert_called_once_with("My_docs")
    create_call = mock_client.collections.create
    create_call.assert_called_once()
    kwargs = create_call.call_args.kwargs
    assert kwargs["name"] == "My_docs"
    assert kwargs["description"] == "Test collection"


def test_create_collection_skips_if_exists():
    """create_collection() is a no-op when the class already exists."""
    mock_client = _mock_client()
    mock_client.collections.exists.return_value = True

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        backend.create_collection("existing", dimension=4)

    mock_client.collections.create.assert_not_called()


def test_create_collection_uses_none_vectorizer():
    """Vectorizer must be set to 'none' — we manage embeddings externally."""
    import weaviate.classes.config as wcc

    mock_client = _mock_client()
    mock_client.collections.exists.return_value = False

    with patch("weaviate.connect_to_local", return_value=mock_client):
        with patch.object(wcc.Configure.Vectorizer, "none", return_value="none_config") as mock_none:
            backend = _make_backend()
            backend.connect()
            backend.create_collection("vecs", dimension=128)
            mock_none.assert_called_once()


# ── insert() ─────────────────────────────────────────────────────────────────


def test_insert_calls_data_insert_with_vector():
    """insert() should call collection.data.insert with properties and vector."""
    mock_client = _mock_client()
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    # aggregate.over_all returns a result with total_count
    mock_col.aggregate.over_all.return_value.total_count = 1

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        count = backend.insert("articles", "doc-1", "Hello world", _v(1.0), {"tag": "test"})

    mock_client.collections.get.assert_called_with("Articles")
    call_kwargs = mock_col.data.insert.call_args.kwargs
    assert call_kwargs["uuid"] == _doc_uuid("doc-1")
    assert call_kwargs["vector"] == _v(1.0)
    props = call_kwargs["properties"]
    assert props["doc_id"] == "doc-1"
    assert props["content"] == "Hello world"
    assert json.loads(props["metadata"]) == {"tag": "test"}
    assert count == 1


def test_insert_returns_new_count():
    """insert() should return the post-insert document count."""
    mock_client = _mock_client()
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.aggregate.over_all.return_value.total_count = 3

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        count = backend.insert("test", "d1", "text", _v(0.5), {})

    assert count == 3


# ── insert_batch() ────────────────────────────────────────────────────────────


def test_insert_batch_calls_insert_many():
    """insert_batch() should use collection.data.insert_many."""
    mock_client = _mock_client()
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.data.insert_many.return_value.errors = {}

    ids = ["a", "b", "c"]
    contents = ["alpha", "beta", "gamma"]
    embeddings = [_v(1.0), _v(0.0, 1.0), _v(0.0, 0.0, 1.0)]
    metadatas = [{"i": "0"}, {"i": "1"}, {"i": "2"}]

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        result = backend.insert_batch("articles", ids, contents, embeddings, metadatas)

    mock_col.data.insert_many.assert_called_once()
    assert result == 3  # len(ids) - 0 errors


def test_insert_batch_empty_returns_zero():
    """insert_batch() with empty lists should return 0 without calling the API."""
    mock_client = _mock_client()
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        result = backend.insert_batch("articles", [], [], [], [])

    mock_col.data.insert_many.assert_not_called()
    assert result == 0


# ── search() ─────────────────────────────────────────────────────────────────


def _make_search_object(doc_id: str, content: str, metadata: dict, certainty: float) -> MagicMock:
    """Build a mock Weaviate query result object."""
    obj = MagicMock()
    obj.properties = {
        "doc_id": doc_id,
        "content": content,
        "metadata": json.dumps(metadata),
    }
    obj.metadata.certainty = certainty
    return obj


def test_search_calls_near_vector():
    """search() should call collection.query.near_vector with the query vector."""
    mock_client = _mock_client()
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.query.near_vector.return_value.objects = [
        _make_search_object("doc-1", "content one", {"k": "v"}, 0.95),
    ]

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        results = backend.search("articles", _v(1.0), limit=5)

    mock_col.query.near_vector.assert_called_once()
    call_kwargs = mock_col.query.near_vector.call_args.kwargs
    assert call_kwargs["near_vector"] == _v(1.0)
    assert call_kwargs["limit"] == 5


def test_search_returns_correct_structure():
    """search() results must have id, content, metadata, similarity keys."""
    mock_client = _mock_client()
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.query.near_vector.return_value.objects = [
        _make_search_object("doc-42", "hello world", {"source": "test"}, 0.88),
    ]

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        results = backend.search("docs", _v(1.0))

    assert len(results) == 1
    r = results[0]
    assert r["id"] == "doc-42"
    assert r["content"] == "hello world"
    assert r["metadata"] == {"source": "test"}
    assert r["similarity"] == pytest.approx(0.88)


def test_search_similarity_in_0_to_1():
    """All similarity scores must be normalised to [0, 1]."""
    mock_client = _mock_client()
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.query.near_vector.return_value.objects = [
        _make_search_object("d1", "text", {}, 1.0),
        _make_search_object("d2", "text", {}, 0.5),
        _make_search_object("d3", "text", {}, 0.0),
    ]

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        results = backend.search("col", _v(1.0))

    for r in results:
        assert 0.0 <= r["similarity"] <= 1.0, f"Out of range: {r['similarity']}"


def test_search_with_filter_builds_weaviate_filter():
    """search() with filters should call Filter.by_property().equal()."""
    mock_client = _mock_client()
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.query.near_vector.return_value.objects = []

    with patch("weaviate.connect_to_local", return_value=mock_client):
        with patch("weaviate.classes.query.Filter") as mock_filter_cls:
            mock_filter_instance = MagicMock()
            mock_filter_cls.by_property.return_value.equal.return_value = mock_filter_instance

            backend = _make_backend()
            backend.connect()
            backend.search("col", _v(1.0), filters={"tag": "alpha"})

    mock_filter_cls.by_property.assert_called_with("tag")
    mock_filter_cls.by_property.return_value.equal.assert_called_with("alpha")


# ── get() ─────────────────────────────────────────────────────────────────────


def test_get_fetches_by_uuid():
    """get() should call fetch_object_by_id with the deterministic UUID."""
    mock_client = _mock_client()
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col

    mock_obj = MagicMock()
    mock_obj.properties = {
        "doc_id": "doc-5",
        "content": "some text",
        "metadata": json.dumps({"x": 1}),
    }
    mock_col.query.fetch_object_by_id.return_value = mock_obj

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        result = backend.get("articles", "doc-5")

    mock_col.query.fetch_object_by_id.assert_called_once_with(_doc_uuid("doc-5"))
    assert result is not None
    assert result["id"] == "doc-5"
    assert result["content"] == "some text"
    assert result["metadata"] == {"x": 1}


def test_get_returns_none_when_not_found():
    """get() should return None when the object does not exist."""
    mock_client = _mock_client()
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.query.fetch_object_by_id.return_value = None

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        result = backend.get("articles", "ghost-id")

    assert result is None


def test_get_returns_none_on_exception():
    """get() should return None if the Weaviate call throws."""
    mock_client = _mock_client()
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.query.fetch_object_by_id.side_effect = Exception("not found")

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        result = backend.get("articles", "doc-99")

    assert result is None


# ── update() ─────────────────────────────────────────────────────────────────


def test_update_calls_replace_when_exists():
    """update() should call data.replace() with new content and vector."""
    mock_client = _mock_client()
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.data.exists.return_value = True

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        result = backend.update("docs", "doc-1", "new content", _v(0.5, 0.5), {"v": 2})

    assert result is True
    mock_col.data.exists.assert_called_once_with(_doc_uuid("doc-1"))
    replace_kwargs = mock_col.data.replace.call_args.kwargs
    assert replace_kwargs["uuid"] == _doc_uuid("doc-1")
    assert replace_kwargs["vector"] == _v(0.5, 0.5)
    assert replace_kwargs["properties"]["content"] == "new content"
    assert json.loads(replace_kwargs["properties"]["metadata"]) == {"v": 2}


def test_update_returns_false_when_not_found():
    """update() should return False without calling replace when doc missing."""
    mock_client = _mock_client()
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.data.exists.return_value = False

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        result = backend.update("docs", "ghost", "text", _v(1.0), {})

    assert result is False
    mock_col.data.replace.assert_not_called()


# ── delete() ─────────────────────────────────────────────────────────────────


def test_delete_calls_delete_by_id_when_exists():
    """delete() should call data.delete_by_id when the object exists."""
    mock_client = _mock_client()
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.data.exists.return_value = True
    mock_col.data.delete_by_id.return_value = True

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        result = backend.delete("docs", "doc-1")

    assert result is True
    mock_col.data.exists.assert_called_once_with(_doc_uuid("doc-1"))
    mock_col.data.delete_by_id.assert_called_once_with(_doc_uuid("doc-1"))


def test_delete_returns_false_when_not_found():
    """delete() should return False without calling delete_by_id when missing."""
    mock_client = _mock_client()
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.data.exists.return_value = False

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        result = backend.delete("docs", "ghost-id")

    assert result is False
    mock_col.data.delete_by_id.assert_not_called()


# ── delete_collection() ───────────────────────────────────────────────────────


def test_delete_collection_returns_doc_count():
    """delete_collection() should return the pre-deletion document count."""
    mock_client = _mock_client()
    mock_client.collections.exists.return_value = True
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.aggregate.over_all.return_value.total_count = 7

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        count = backend.delete_collection("articles")

    assert count == 7
    mock_client.collections.delete.assert_called_once_with("Articles")


def test_delete_collection_returns_zero_if_missing():
    """delete_collection() on a non-existent collection returns 0."""
    mock_client = _mock_client()
    mock_client.collections.exists.return_value = False

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        count = backend.delete_collection("does_not_exist")

    assert count == 0
    mock_client.collections.delete.assert_not_called()


# ── list_collections() ────────────────────────────────────────────────────────


def test_list_collections_returns_names_and_counts():
    """list_collections() should return dicts with 'name' and 'count'."""
    mock_client = _mock_client()

    # list_all returns a dict of {class_name: config}
    config_mock = MagicMock()
    config_mock.description = None
    mock_client.collections.list_all.return_value = {"Articles": config_mock}

    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.aggregate.over_all.return_value.total_count = 5

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        result = backend.list_collections()

    assert len(result) == 1
    assert result[0]["name"] == "Articles"
    assert result[0]["count"] == 5


def test_list_collections_includes_description():
    """list_collections() should include description when present."""
    mock_client = _mock_client()
    config_mock = MagicMock()
    config_mock.description = "My test collection"
    mock_client.collections.list_all.return_value = {"Docs": config_mock}

    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.aggregate.over_all.return_value.total_count = 0

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        result = backend.list_collections()

    assert result[0].get("description") == "My test collection"


# ── collection_count() ────────────────────────────────────────────────────────


def test_collection_count_returns_count():
    """collection_count() should return the aggregate total_count."""
    mock_client = _mock_client()
    mock_client.collections.exists.return_value = True
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.aggregate.over_all.return_value.total_count = 42

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        count = backend.collection_count("articles")

    assert count == 42


def test_collection_count_returns_zero_for_missing():
    """collection_count() returns 0 if the collection does not exist."""
    mock_client = _mock_client()
    mock_client.collections.exists.return_value = False

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        count = backend.collection_count("no_such_collection")

    assert count == 0


# ── collection_peek() ─────────────────────────────────────────────────────────


def _make_peek_object(doc_id: str, content: str, metadata: dict) -> MagicMock:
    obj = MagicMock()
    obj.properties = {
        "doc_id": doc_id,
        "content": content,
        "metadata": json.dumps(metadata),
    }
    return obj


def test_collection_peek_returns_documents():
    """collection_peek() should return docs with id, content, metadata."""
    mock_client = _mock_client()
    mock_client.collections.exists.return_value = True
    mock_col = MagicMock()
    mock_client.collections.get.return_value = mock_col
    mock_col.query.fetch_objects.return_value.objects = [
        _make_peek_object("doc-1", "first doc", {"k": "v"}),
    ]

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        result = backend.collection_peek("articles", limit=5)

    mock_col.query.fetch_objects.assert_called_once_with(limit=5)
    assert len(result) == 1
    assert result[0]["id"] == "doc-1"
    assert result[0]["content"] == "first doc"
    assert result[0]["metadata"] == {"k": "v"}


def test_collection_peek_returns_empty_for_missing_collection():
    """collection_peek() returns [] when the collection does not exist."""
    mock_client = _mock_client()
    mock_client.collections.exists.return_value = False

    with patch("weaviate.connect_to_local", return_value=mock_client):
        backend = _make_backend()
        backend.connect()
        result = backend.collection_peek("nonexistent")

    assert result == []
