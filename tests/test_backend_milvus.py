"""Tests for the Milvus v2 backend.

All tests mock MilvusClient — no running Milvus server is required.
The mocks validate that MilvusBackend calls the correct client methods with
the correct arguments and that all return values conform to the MemoryBackend
contract.

The entire module is skipped gracefully when pymilvus is not installed.
"""

import json
from unittest.mock import MagicMock, patch, call

import pytest

try:
    from pymilvus import MilvusClient  # noqa: F401
    HAS_MILVUS = True
except ImportError:
    HAS_MILVUS = False

pytestmark = pytest.mark.skipif(not HAS_MILVUS, reason="pymilvus not installed")

from ember_memory.core.backends.milvus_backend import (  # noqa: E402
    MilvusBackend,
    _build_filter_expr,
    _normalise_score,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _v(*args: float) -> list[float]:
    """4-dimensional test vector, padded with zeros."""
    base = list(args) + [0.0] * 4
    return base[:4]


def _make_backend(
    uri: str = "http://localhost:19530",
    token: str = "",
    db_name: str = "ember_memory",
) -> MilvusBackend:
    return MilvusBackend(uri=uri, token=token, db_name=db_name)


def _mock_milvus_client() -> MagicMock:
    """Return a MagicMock that mimics MilvusClient well enough for these tests."""
    client = MagicMock(spec=MilvusClient)
    # list_databases returns the default db list.
    client.list_databases.return_value = ["default", "ember_memory"]
    # has_collection defaults to False (collection doesn't exist yet).
    client.has_collection.return_value = False
    # list_collections defaults to empty.
    client.list_collections.return_value = []
    # Schema builder chain.
    mock_schema = MagicMock()
    client.create_schema.return_value = mock_schema
    # Index params builder chain.
    mock_index_params = MagicMock()
    client.prepare_index_params.return_value = mock_index_params
    # get_collection_stats defaults to 0 documents.
    client.get_collection_stats.return_value = {"row_count": 0}
    # insert/upsert/delete return success dicts.
    client.insert.return_value = {"insert_count": 1}
    client.upsert.return_value = {"upsert_count": 1}
    client.delete.return_value = {"delete_count": 1}
    # get/query/search default to empty lists.
    client.get.return_value = []
    client.query.return_value = []
    client.search.return_value = [[]]
    return client


def _connected_backend(mock_client: MagicMock | None = None) -> tuple[MilvusBackend, MagicMock]:
    """Return a connected backend and its injected mock client."""
    if mock_client is None:
        mock_client = _mock_milvus_client()
    backend = _make_backend()
    with patch("ember_memory.core.backends.milvus_backend.MilvusClient", return_value=mock_client):
        backend.connect()
    return backend, mock_client


# ── Utility function tests ────────────────────────────────────────────────────


def test_normalise_score_maps_minus1_to_0():
    assert _normalise_score(-1.0) == pytest.approx(0.0)


def test_normalise_score_maps_1_to_1():
    assert _normalise_score(1.0) == pytest.approx(1.0)


def test_normalise_score_maps_0_to_half():
    assert _normalise_score(0.0) == pytest.approx(0.5)


def test_normalise_score_clamps_below_zero():
    assert _normalise_score(-2.0) == 0.0


def test_normalise_score_clamps_above_one():
    assert _normalise_score(3.0) == 1.0


def test_build_filter_expr_single_string():
    expr = _build_filter_expr({"tag": "hello"})
    assert expr == 'tag == "hello"'


def test_build_filter_expr_numeric_value():
    expr = _build_filter_expr({"count": 42})
    assert expr == "count == 42"


def test_build_filter_expr_multiple_fields():
    expr = _build_filter_expr({"a": "x", "b": "y"})
    # Both clauses must appear, joined with " and "
    assert "a" in expr and "b" in expr
    assert " and " in expr


def test_build_filter_expr_empty_returns_empty():
    assert _build_filter_expr({}) == ""


# ── Interface compliance ───────────────────────────────────────────────────────


def test_implements_memory_backend_interface():
    from ember_memory.core.backends.base import MemoryBackend
    assert issubclass(MilvusBackend, MemoryBackend)


def test_require_client_raises_before_connect():
    """Any method before connect() must raise RuntimeError."""
    backend = _make_backend()
    with pytest.raises(RuntimeError, match="connect"):
        backend.create_collection("test", dimension=4)


# ── connect() ────────────────────────────────────────────────────────────────


def test_connect_creates_milvus_client():
    mock_client = _mock_milvus_client()
    backend = _make_backend(uri="http://localhost:19530", token="")
    with patch(
        "ember_memory.core.backends.milvus_backend.MilvusClient", return_value=mock_client
    ) as mock_cls:
        backend.connect()
        mock_cls.assert_called_once_with(uri="http://localhost:19530")
    assert backend._client is mock_client


def test_connect_passes_token_when_provided():
    mock_client = _mock_milvus_client()
    backend = _make_backend(uri="https://cloud.zilliz.com", token="my-api-key")
    with patch(
        "ember_memory.core.backends.milvus_backend.MilvusClient", return_value=mock_client
    ) as mock_cls:
        backend.connect()
        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs.get("token") == "my-api-key"


def test_connect_raises_on_connection_failure():
    backend = _make_backend()
    with patch(
        "ember_memory.core.backends.milvus_backend.MilvusClient",
        side_effect=Exception("connection refused"),
    ):
        with pytest.raises(RuntimeError, match="failed to connect"):
            backend.connect()


def test_connect_stores_client():
    backend, mock_client = _connected_backend()
    assert backend._client is mock_client


# ── create_collection() ───────────────────────────────────────────────────────


def test_create_collection_calls_create_schema():
    backend, mock_client = _connected_backend()
    backend.create_collection("my_docs", dimension=128)
    mock_client.create_schema.assert_called_once()


def test_create_collection_calls_prepare_index_params():
    backend, mock_client = _connected_backend()
    backend.create_collection("my_docs", dimension=128)
    mock_client.prepare_index_params.assert_called_once()


def test_create_collection_calls_create_collection():
    backend, mock_client = _connected_backend()
    backend.create_collection("my_docs", dimension=128)
    mock_client.create_collection.assert_called_once()
    kwargs = mock_client.create_collection.call_args.kwargs
    assert kwargs["collection_name"] == "my_docs"


def test_create_collection_schema_includes_all_fields():
    """Schema must include id, content, metadata, and embedding fields."""
    backend, mock_client = _connected_backend()
    mock_schema = mock_client.create_schema.return_value
    backend.create_collection("docs", dimension=64)
    # add_field should have been called at least 4 times.
    assert mock_schema.add_field.call_count >= 4
    added_field_names = [
        c.kwargs.get("field_name", c.args[0] if c.args else "")
        for c in mock_schema.add_field.call_args_list
    ]
    assert "id" in added_field_names
    assert "content" in added_field_names
    assert "metadata" in added_field_names
    assert "embedding" in added_field_names


def test_create_collection_hnsw_index_on_embedding():
    """HNSW index must be added to the embedding field with COSINE metric."""
    backend, mock_client = _connected_backend()
    mock_index_params = mock_client.prepare_index_params.return_value
    backend.create_collection("docs", dimension=64)
    mock_index_params.add_index.assert_called_once()
    call_kwargs = mock_index_params.add_index.call_args.kwargs
    assert call_kwargs["field_name"] == "embedding"
    assert call_kwargs["index_type"] == "HNSW"
    assert call_kwargs["metric_type"] == "COSINE"


def test_create_collection_is_idempotent():
    """create_collection() should be a no-op if the collection already exists."""
    backend, mock_client = _connected_backend()
    mock_client.has_collection.return_value = True
    backend.create_collection("existing", dimension=4)
    mock_client.create_collection.assert_not_called()


def test_create_collection_stores_description():
    backend, mock_client = _connected_backend()
    backend.create_collection("notes", dimension=32, description="A test collection")
    assert backend._descriptions.get("notes") == "A test collection"


def test_create_collection_stores_dimension():
    backend, mock_client = _connected_backend()
    backend.create_collection("vecs", dimension=256)
    assert backend._dimensions.get("vecs") == 256


# ── delete_collection() ───────────────────────────────────────────────────────


def test_delete_collection_returns_doc_count():
    backend, mock_client = _connected_backend()
    mock_client.has_collection.return_value = True
    mock_client.get_collection_stats.return_value = {"row_count": 7}
    count = backend.delete_collection("articles")
    assert count == 7
    mock_client.drop_collection.assert_called_once_with("articles")


def test_delete_collection_returns_zero_if_missing():
    backend, mock_client = _connected_backend()
    mock_client.has_collection.return_value = False
    count = backend.delete_collection("no_such")
    assert count == 0
    mock_client.drop_collection.assert_not_called()


def test_delete_collection_clears_dimension_cache():
    backend, mock_client = _connected_backend()
    mock_client.has_collection.return_value = True
    mock_client.get_collection_stats.return_value = {"row_count": 0}
    backend._dimensions["to_delete"] = 128
    backend.delete_collection("to_delete")
    assert "to_delete" not in backend._dimensions


def test_delete_collection_clears_description_cache():
    backend, mock_client = _connected_backend()
    mock_client.has_collection.return_value = True
    mock_client.get_collection_stats.return_value = {"row_count": 0}
    backend._descriptions["to_delete"] = "some desc"
    backend.delete_collection("to_delete")
    assert "to_delete" not in backend._descriptions


# ── list_collections() ────────────────────────────────────────────────────────


def test_list_collections_returns_names_and_counts():
    backend, mock_client = _connected_backend()
    mock_client.list_collections.return_value = ["col_a", "col_b"]
    mock_client.get_collection_stats.side_effect = [
        {"row_count": 3},
        {"row_count": 5},
    ]
    result = backend.list_collections()
    assert len(result) == 2
    by_name = {r["name"]: r for r in result}
    assert by_name["col_a"]["count"] == 3
    assert by_name["col_b"]["count"] == 5


def test_list_collections_includes_description():
    backend, mock_client = _connected_backend()
    mock_client.list_collections.return_value = ["annotated"]
    mock_client.get_collection_stats.return_value = {"row_count": 0}
    backend._descriptions["annotated"] = "My description"
    result = backend.list_collections()
    assert result[0].get("description") == "My description"


def test_list_collections_empty():
    backend, mock_client = _connected_backend()
    mock_client.list_collections.return_value = []
    assert backend.list_collections() == []


# ── insert() ─────────────────────────────────────────────────────────────────


def test_insert_calls_milvus_insert():
    backend, mock_client = _connected_backend()
    mock_client.get_collection_stats.return_value = {"row_count": 1}
    count = backend.insert("col", "doc-1", "hello world", _v(1.0), {"tag": "x"})
    mock_client.insert.assert_called_once()
    call_kwargs = mock_client.insert.call_args.kwargs
    assert call_kwargs["collection_name"] == "col"
    data = call_kwargs["data"]
    assert data["id"] == "doc-1"
    assert data["content"] == "hello world"
    assert json.loads(data["metadata"]) == {"tag": "x"}
    assert data["embedding"] == _v(1.0)
    assert count == 1


def test_insert_returns_new_count():
    backend, mock_client = _connected_backend()
    mock_client.get_collection_stats.return_value = {"row_count": 5}
    count = backend.insert("col", "d", "text", _v(0.5), {})
    assert count == 5


def test_insert_serialises_metadata_as_json():
    backend, mock_client = _connected_backend()
    mock_client.get_collection_stats.return_value = {"row_count": 1}
    meta = {"key": "value", "num": 42}
    backend.insert("col", "doc-2", "content", _v(1.0), meta)
    data = mock_client.insert.call_args.kwargs["data"]
    parsed = json.loads(data["metadata"])
    assert parsed == meta


# ── insert_batch() ────────────────────────────────────────────────────────────


def test_insert_batch_calls_insert_once():
    backend, mock_client = _connected_backend()
    ids = ["a", "b", "c"]
    contents = ["alpha", "beta", "gamma"]
    embeddings = [_v(1.0), _v(0.0, 1.0), _v(0.0, 0.0, 1.0)]
    metadatas = [{"i": "0"}, {"i": "1"}, {"i": "2"}]
    result = backend.insert_batch("col", ids, contents, embeddings, metadatas)
    mock_client.insert.assert_called_once()
    assert result == 3


def test_insert_batch_passes_all_records():
    backend, mock_client = _connected_backend()
    ids = ["x", "y"]
    contents = ["foo", "bar"]
    embeddings = [_v(1.0), _v(0.0, 1.0)]
    metadatas = [{"k": "1"}, {"k": "2"}]
    backend.insert_batch("col", ids, contents, embeddings, metadatas)
    data_arg = mock_client.insert.call_args.kwargs["data"]
    assert len(data_arg) == 2
    assert data_arg[0]["id"] == "x"
    assert data_arg[1]["id"] == "y"


def test_insert_batch_empty_returns_zero():
    backend, mock_client = _connected_backend()
    result = backend.insert_batch("col", [], [], [], [])
    mock_client.insert.assert_not_called()
    assert result == 0


# ── update() ─────────────────────────────────────────────────────────────────


def test_update_returns_true_when_exists():
    backend, mock_client = _connected_backend()
    mock_client.get.return_value = [{"id": "doc-1", "content": "old", "metadata": "{}"}]
    result = backend.update("col", "doc-1", "new content", _v(0.5), {"v": 2})
    assert result is True
    mock_client.upsert.assert_called_once()


def test_update_returns_false_when_not_found():
    backend, mock_client = _connected_backend()
    mock_client.get.return_value = []
    result = backend.update("col", "ghost", "content", _v(1.0), {})
    assert result is False
    mock_client.upsert.assert_not_called()


def test_update_calls_upsert_with_correct_data():
    backend, mock_client = _connected_backend()
    mock_client.get.return_value = [{"id": "doc-1"}]
    backend.update("col", "doc-1", "updated", _v(0.0, 1.0), {"key": "val"})
    upsert_data = mock_client.upsert.call_args.kwargs["data"]
    assert upsert_data["id"] == "doc-1"
    assert upsert_data["content"] == "updated"
    assert json.loads(upsert_data["metadata"]) == {"key": "val"}
    assert upsert_data["embedding"] == _v(0.0, 1.0)


# ── delete() ─────────────────────────────────────────────────────────────────


def test_delete_returns_true_when_exists():
    backend, mock_client = _connected_backend()
    mock_client.get.return_value = [{"id": "doc-1"}]
    result = backend.delete("col", "doc-1")
    assert result is True
    mock_client.delete.assert_called_once_with(collection_name="col", ids=["doc-1"])


def test_delete_returns_false_when_not_found():
    backend, mock_client = _connected_backend()
    mock_client.get.return_value = []
    result = backend.delete("col", "ghost")
    assert result is False
    mock_client.delete.assert_not_called()


# ── search() ─────────────────────────────────────────────────────────────────


def _make_hit(doc_id: str, content: str, metadata: dict, distance: float) -> dict:
    """Build a mock Milvus search hit dict."""
    return {
        "id": doc_id,
        "distance": distance,
        "entity": {
            "id": doc_id,
            "content": content,
            "metadata": json.dumps(metadata),
        },
    }


def test_search_calls_milvus_search():
    backend, mock_client = _connected_backend()
    mock_client.search.return_value = [[]]
    backend.search("col", _v(1.0), limit=5)
    mock_client.search.assert_called_once()
    kwargs = mock_client.search.call_args.kwargs
    assert kwargs["collection_name"] == "col"
    assert kwargs["data"] == [_v(1.0)]
    assert kwargs["anns_field"] == "embedding"
    assert kwargs["limit"] == 5


def test_search_returns_correct_structure():
    backend, mock_client = _connected_backend()
    mock_client.search.return_value = [[
        _make_hit("doc-42", "hello world", {"source": "test"}, 0.75),
    ]]
    results = backend.search("col", _v(1.0))
    assert len(results) == 1
    r = results[0]
    assert r["id"] == "doc-42"
    assert r["content"] == "hello world"
    assert r["metadata"] == {"source": "test"}
    assert 0.0 <= r["similarity"] <= 1.0


def test_search_normalises_similarity():
    """Cosine distance=1.0 → similarity should be (1+1)/2 = 1.0."""
    backend, mock_client = _connected_backend()
    mock_client.search.return_value = [[_make_hit("d", "c", {}, 1.0)]]
    results = backend.search("col", _v(1.0))
    assert results[0]["similarity"] == pytest.approx(1.0)


def test_search_similarity_range():
    backend, mock_client = _connected_backend()
    mock_client.search.return_value = [[
        _make_hit("d1", "t", {}, 1.0),
        _make_hit("d2", "t", {}, 0.0),
        _make_hit("d3", "t", {}, -1.0),
    ]]
    results = backend.search("col", _v(1.0), limit=3)
    for r in results:
        assert 0.0 <= r["similarity"] <= 1.0, f"Out of range: {r['similarity']}"


def test_search_empty_collection_returns_empty():
    backend, mock_client = _connected_backend()
    mock_client.search.return_value = [[]]
    results = backend.search("col", _v(1.0))
    assert results == []


def test_search_passes_filter_expression():
    backend, mock_client = _connected_backend()
    mock_client.search.return_value = [[]]
    backend.search("col", _v(1.0), filters={"tag": "alpha"})
    kwargs = mock_client.search.call_args.kwargs
    assert "alpha" in kwargs.get("filter", "")


def test_search_no_filter_passes_empty_string():
    backend, mock_client = _connected_backend()
    mock_client.search.return_value = [[]]
    backend.search("col", _v(1.0))
    kwargs = mock_client.search.call_args.kwargs
    assert kwargs.get("filter", "") == ""


# ── get() ─────────────────────────────────────────────────────────────────────


def test_get_calls_milvus_get():
    backend, mock_client = _connected_backend()
    mock_client.get.return_value = [
        {"id": "doc-5", "content": "some text", "metadata": json.dumps({"x": 1})}
    ]
    result = backend.get("articles", "doc-5")
    mock_client.get.assert_called_once_with(
        collection_name="articles",
        ids=["doc-5"],
        output_fields=["id", "content", "metadata"],
    )
    assert result is not None
    assert result["id"] == "doc-5"
    assert result["content"] == "some text"
    assert result["metadata"] == {"x": 1}


def test_get_returns_none_when_not_found():
    backend, mock_client = _connected_backend()
    mock_client.get.return_value = []
    result = backend.get("articles", "ghost")
    assert result is None


def test_get_deserialises_metadata():
    backend, mock_client = _connected_backend()
    meta = {"flag": True, "score": 3.14}
    mock_client.get.return_value = [
        {"id": "d", "content": "c", "metadata": json.dumps(meta)}
    ]
    result = backend.get("col", "d")
    assert result["metadata"] == meta


# ── collection_count() ────────────────────────────────────────────────────────


def test_collection_count_returns_row_count():
    backend, mock_client = _connected_backend()
    mock_client.has_collection.return_value = True
    mock_client.get_collection_stats.return_value = {"row_count": 42}
    assert backend.collection_count("articles") == 42


def test_collection_count_returns_zero_for_missing():
    backend, mock_client = _connected_backend()
    mock_client.has_collection.return_value = False
    assert backend.collection_count("no_such") == 0


def test_collection_count_returns_zero_on_stats_error():
    backend, mock_client = _connected_backend()
    mock_client.has_collection.return_value = True
    mock_client.get_collection_stats.side_effect = Exception("error")
    assert backend.collection_count("col") == 0


# ── collection_peek() ─────────────────────────────────────────────────────────


def test_collection_peek_returns_documents():
    backend, mock_client = _connected_backend()
    mock_client.has_collection.return_value = True
    mock_client.query.return_value = [
        {"id": "doc-1", "content": "first", "metadata": json.dumps({"k": "v"})},
    ]
    result = backend.collection_peek("articles", limit=5)
    mock_client.query.assert_called_once()
    assert len(result) == 1
    assert result[0]["id"] == "doc-1"
    assert result[0]["content"] == "first"
    assert result[0]["metadata"] == {"k": "v"}


def test_collection_peek_respects_limit():
    backend, mock_client = _connected_backend()
    mock_client.has_collection.return_value = True
    mock_client.query.return_value = [
        {"id": f"d{i}", "content": f"c{i}", "metadata": "{}"}
        for i in range(3)
    ]
    result = backend.collection_peek("col", limit=3)
    kwargs = mock_client.query.call_args.kwargs
    assert kwargs.get("limit") == 3
    assert len(result) <= 3


def test_collection_peek_returns_empty_for_missing():
    backend, mock_client = _connected_backend()
    mock_client.has_collection.return_value = False
    result = backend.collection_peek("nonexistent")
    assert result == []
    mock_client.query.assert_not_called()


def test_collection_peek_returns_empty_on_query_error():
    backend, mock_client = _connected_backend()
    mock_client.has_collection.return_value = True
    mock_client.query.side_effect = Exception("query failed")
    result = backend.collection_peek("col")
    assert result == []
