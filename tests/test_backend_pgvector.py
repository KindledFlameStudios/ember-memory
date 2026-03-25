"""Tests for the PostgreSQL + pgvector v2 backend.

All tests mock psycopg2.connect and the cursor — no running PostgreSQL server
is required. The mocks validate that PgvectorBackend issues the correct SQL,
uses parameterised queries for all data values, and correctly parses results.

Skip the entire module gracefully if psycopg2 is not installed.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest

try:
    import psycopg2  # noqa: F401
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

pytestmark = pytest.mark.skipif(not HAS_PSYCOPG2, reason="psycopg2 not installed")

from ember_memory.core.backends.pgvector_backend import (  # noqa: E402
    PgvectorBackend,
    _validate_name,
    _vec_to_pg,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _v(*args: float) -> list[float]:
    """Return a 4-dimensional test vector, padding with zeros."""
    base = list(args) + [0.0] * 4
    return base[:4]


def _make_mock_conn() -> MagicMock:
    """Return a mock psycopg2 connection with a context-manager cursor."""
    conn = MagicMock()
    cursor = MagicMock()
    # cursor() acts as a context manager: __enter__ returns the cursor itself
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor
    return conn


def _make_backend(**kwargs) -> PgvectorBackend:
    return PgvectorBackend(**kwargs)


def _connected_backend(mock_conn: MagicMock) -> PgvectorBackend:
    """Return a PgvectorBackend with connect() already called using *mock_conn*."""
    backend = _make_backend()
    with patch("psycopg2.connect", return_value=mock_conn):
        backend.connect()
    # Reset call counts so tests only see post-connect calls
    mock_conn.reset_mock()
    return backend


# ── Utility function tests ────────────────────────────────────────────────────


def test_vec_to_pg_formats_correctly():
    assert _vec_to_pg([1.0, 0.0, 0.5]) == "[1.0,0.0,0.5]"


def test_vec_to_pg_single_element():
    assert _vec_to_pg([0.75]) == "[0.75]"


def test_validate_name_accepts_valid():
    assert _validate_name("my_collection") == "my_collection"
    assert _validate_name("col123") == "col123"
    assert _validate_name("_private") == "_private"


def test_validate_name_rejects_hyphen():
    with pytest.raises(ValueError, match="Invalid collection name"):
        _validate_name("bad-name")


def test_validate_name_rejects_leading_digit():
    with pytest.raises(ValueError, match="Invalid collection name"):
        _validate_name("1invalid")


def test_validate_name_rejects_sql_injection():
    with pytest.raises(ValueError, match="Invalid collection name"):
        _validate_name("docs; DROP TABLE docs--")


# ── Interface compliance ───────────────────────────────────────────────────────


def test_implements_memory_backend_interface():
    from ember_memory.core.backends.base import MemoryBackend
    assert issubclass(PgvectorBackend, MemoryBackend)


# ── connect() ────────────────────────────────────────────────────────────────


def test_connect_uses_dsn_when_provided():
    """connect() should pass the DSN string directly to psycopg2.connect."""
    mock_conn = _make_mock_conn()
    backend = _make_backend(dsn="host=myhost dbname=mydb user=me")
    with patch("psycopg2.connect", return_value=mock_conn) as mock_connect:
        backend.connect()
    mock_connect.assert_called_once_with("host=myhost dbname=mydb user=me")


def test_connect_builds_kwargs_without_dsn():
    """connect() should build keyword arguments from host/port/dbname/user/password."""
    mock_conn = _make_mock_conn()
    backend = _make_backend(
        host="pghost",
        port=5433,
        dbname="testdb",
        user="alice",
        password="secret",
    )
    with patch("psycopg2.connect", return_value=mock_conn) as mock_connect:
        backend.connect()
    mock_connect.assert_called_once_with(
        host="pghost",
        port=5433,
        dbname="testdb",
        user="alice",
        password="secret",
    )


def test_connect_omits_empty_user_and_password():
    """Empty user/password should not be passed to psycopg2.connect."""
    mock_conn = _make_mock_conn()
    backend = _make_backend(host="h", port=5432, dbname="d")
    with patch("psycopg2.connect", return_value=mock_conn) as mock_connect:
        backend.connect()
    call_kwargs = mock_connect.call_args.kwargs
    assert "user" not in call_kwargs
    assert "password" not in call_kwargs


def test_connect_creates_vector_extension():
    """connect() should execute CREATE EXTENSION IF NOT EXISTS vector."""
    mock_conn = _make_mock_conn()
    backend = _make_backend()
    with patch("psycopg2.connect", return_value=mock_conn):
        backend.connect()
    cur = mock_conn.cursor.return_value.__enter__.return_value
    executed_sql = " ".join(c.args[0] for c in cur.execute.call_args_list)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in executed_sql


def test_connect_required_before_use():
    """Any method called before connect() must raise RuntimeError."""
    backend = _make_backend()
    with pytest.raises(RuntimeError, match="connect"):
        backend.create_collection("test", dimension=4)


# ── create_collection() ───────────────────────────────────────────────────────


def test_create_collection_issues_create_table():
    """create_collection() should issue CREATE TABLE IF NOT EXISTS."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)
    backend.create_collection("my_docs", dimension=384)
    cur = mock_conn.cursor.return_value.__enter__.return_value
    all_sql = " ".join(c.args[0] for c in cur.execute.call_args_list)
    assert "CREATE TABLE IF NOT EXISTS my_docs" in all_sql


def test_create_collection_uses_correct_dimension():
    """The vector column must use the supplied dimension."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)
    backend.create_collection("vecs", dimension=768)
    cur = mock_conn.cursor.return_value.__enter__.return_value
    all_sql = " ".join(c.args[0] for c in cur.execute.call_args_list)
    assert "vector(768)" in all_sql


def test_create_collection_creates_hnsw_index():
    """create_collection() should create an HNSW index with cosine ops."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)
    backend.create_collection("vecs", dimension=128)
    cur = mock_conn.cursor.return_value.__enter__.return_value
    all_sql = " ".join(c.args[0] for c in cur.execute.call_args_list)
    assert "hnsw" in all_sql.lower()
    assert "vector_cosine_ops" in all_sql


def test_create_collection_commits():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)
    backend.create_collection("col", dimension=4)
    mock_conn.commit.assert_called()


def test_create_collection_rejects_invalid_name():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)
    with pytest.raises(ValueError, match="Invalid collection name"):
        backend.create_collection("bad-name", dimension=4)


# ── delete_collection() ───────────────────────────────────────────────────────


def test_delete_collection_issues_drop_table():
    """delete_collection() should issue DROP TABLE IF EXISTS."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    # First call in delete_collection is _table_count → SELECT COUNT(*)
    cur.fetchone.return_value = (3,)

    backend.delete_collection("my_docs")

    all_sql = " ".join(c.args[0] for c in cur.execute.call_args_list)
    assert "DROP TABLE IF EXISTS my_docs" in all_sql


def test_delete_collection_returns_pre_deletion_count():
    """delete_collection() should return the row count that existed before drop."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (7,)

    count = backend.delete_collection("my_docs")
    assert count == 7


def test_delete_collection_returns_zero_when_table_missing():
    """delete_collection() returns 0 when the table does not exist."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    # _table_count will raise (table missing) → returns 0
    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.execute.side_effect = [Exception("table does not exist"), None]

    count = backend.delete_collection("missing_table")
    assert count == 0


# ── list_collections() ────────────────────────────────────────────────────────


def test_list_collections_queries_information_schema():
    """list_collections() should query information_schema.columns."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    # First query: information_schema → two tables
    # Second + third queries: COUNT(*) for each table
    cur.fetchall.return_value = [("docs",), ("notes",)]
    cur.fetchone.return_value = (5,)

    result = backend.list_collections()

    schema_sql = cur.execute.call_args_list[0].args[0]
    assert "information_schema" in schema_sql
    assert "embedding" in schema_sql


def test_list_collections_returns_name_and_count():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [("articles",)]
    cur.fetchone.return_value = (42,)

    result = backend.list_collections()
    assert len(result) == 1
    assert result[0]["name"] == "articles"
    assert result[0]["count"] == 42


def test_list_collections_empty():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    result = backend.list_collections()
    assert result == []


# ── insert() ─────────────────────────────────────────────────────────────────


def test_insert_uses_parameterized_query():
    """insert() must use parameterised SQL — no f-string data interpolation."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (1,)

    backend.insert("my_col", "doc-1", "hello world", _v(1.0), {"tag": "test"})

    # Find the INSERT call
    insert_call = next(
        c for c in cur.execute.call_args_list
        if "INSERT" in c.args[0]
    )
    sql, params = insert_call.args
    # All data values must be passed as parameters, not baked into the SQL
    assert "doc-1" not in sql
    assert "hello world" not in sql
    assert "test" not in sql
    # Verify actual params
    assert params[0] == "doc-1"
    assert params[1] == "hello world"
    assert json.loads(params[2]) == {"tag": "test"}
    # Embedding should be serialised to pgvector format
    assert params[3] == "[1.0,0.0,0.0,0.0]"


def test_insert_returns_new_count():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (3,)

    count = backend.insert("my_col", "d1", "text", _v(1.0), {})
    assert count == 3


def test_insert_uses_cast_vector():
    """Embedding must be cast using ``%s::vector`` not a literal pgvector object."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (1,)

    backend.insert("col", "id1", "text", _v(0.5, 0.5), {})

    insert_call = next(
        c for c in cur.execute.call_args_list
        if "INSERT" in c.args[0]
    )
    sql = insert_call.args[0]
    assert "%s::vector" in sql


# ── insert_batch() ────────────────────────────────────────────────────────────


def test_insert_batch_uses_executemany():
    """insert_batch() should call cursor.executemany for efficiency."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value

    ids = ["a", "b", "c"]
    contents = ["alpha", "beta", "gamma"]
    embeddings = [_v(1.0), _v(0.0, 1.0), _v(0.0, 0.0, 1.0)]
    metadatas = [{"i": "0"}, {"i": "1"}, {"i": "2"}]

    result = backend.insert_batch("col", ids, contents, embeddings, metadatas)

    cur.executemany.assert_called_once()
    assert result == 3


def test_insert_batch_empty_returns_zero():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)
    cur = mock_conn.cursor.return_value.__enter__.return_value

    result = backend.insert_batch("col", [], [], [], [])

    cur.executemany.assert_not_called()
    assert result == 0


def test_insert_batch_serialises_metadata_as_json():
    """Each metadata dict must be serialised to a JSON string for the parameter."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)
    cur = mock_conn.cursor.return_value.__enter__.return_value

    backend.insert_batch(
        "col",
        ["x"],
        ["text"],
        [_v(1.0)],
        [{"k": "v"}],
    )

    rows_arg = cur.executemany.call_args.args[1]
    # rows_arg is a list of tuples: (id, content, metadata_json, vec_str)
    meta_json = rows_arg[0][2]
    assert json.loads(meta_json) == {"k": "v"}


# ── search() ─────────────────────────────────────────────────────────────────


def test_search_uses_cosine_distance_operator():
    """search() must use the <=> operator for cosine distance ordering."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    backend.search("col", _v(1.0), limit=5)

    search_call = next(
        c for c in cur.execute.call_args_list
        if "SELECT" in c.args[0]
    )
    sql = search_call.args[0]
    assert "<=>" in sql


def test_search_selects_similarity_as_1_minus_distance():
    """Similarity must be expressed as ``1 - (embedding <=> ...)``."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    backend.search("col", _v(1.0))

    search_call = next(c for c in cur.execute.call_args_list if "SELECT" in c.args[0])
    sql = search_call.args[0]
    assert "1 -" in sql
    assert "similarity" in sql.lower()


def test_search_passes_limit_as_parameter():
    """The LIMIT value must be passed as a query parameter, not baked into SQL."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    backend.search("col", _v(1.0), limit=7)

    search_call = next(c for c in cur.execute.call_args_list if "SELECT" in c.args[0])
    sql, params = search_call.args
    assert "7" not in sql  # not baked in
    assert 7 in params


def test_search_returns_correct_structure():
    """search() results must have id, content, metadata, similarity."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [
        ("doc-1", "hello world", json.dumps({"src": "test"}), 0.95),
    ]

    results = backend.search("col", _v(1.0), limit=5)

    assert len(results) == 1
    r = results[0]
    assert r["id"] == "doc-1"
    assert r["content"] == "hello world"
    assert r["metadata"] == {"src": "test"}
    assert r["similarity"] == pytest.approx(0.95)


def test_search_similarity_is_float():
    """similarity must be a Python float, not a Decimal or other type."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [
        ("d1", "text", "{}", 0.8),
    ]

    results = backend.search("col", _v(1.0))
    assert isinstance(results[0]["similarity"], float)


def test_search_with_filter_uses_jsonb_containment():
    """Metadata filters should use the @> JSONB containment operator."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    backend.search("col", _v(1.0), filters={"tag": "alpha"})

    search_call = next(c for c in cur.execute.call_args_list if "SELECT" in c.args[0])
    sql, params = search_call.args
    assert "@>" in sql
    # The filter value must be passed as a JSON parameter
    filter_params = [p for p in params if isinstance(p, str) and "alpha" in p]
    assert any(json.loads(p) == {"tag": "alpha"} for p in filter_params)


def test_search_with_multiple_filters():
    """Multiple filters should all appear as WHERE clauses."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    backend.search("col", _v(1.0), filters={"tag": "x", "author": "bob"})

    search_call = next(c for c in cur.execute.call_args_list if "SELECT" in c.args[0])
    sql = search_call.args[0]
    assert sql.count("@>") == 2


def test_search_empty_result():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []

    results = backend.search("col", _v(1.0))
    assert results == []


# ── get() ─────────────────────────────────────────────────────────────────────


def test_get_selects_by_id():
    """get() should issue a SELECT WHERE id = %s with parameterised id."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = ("doc-42", "some text", json.dumps({"x": 1}))

    result = backend.get("col", "doc-42")

    select_call = next(c for c in cur.execute.call_args_list if "SELECT" in c.args[0])
    sql, params = select_call.args
    assert "doc-42" not in sql  # not baked in
    assert params == ("doc-42",)


def test_get_returns_correct_structure():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = ("doc-5", "content here", json.dumps({"k": "v"}))

    result = backend.get("col", "doc-5")

    assert result is not None
    assert result["id"] == "doc-5"
    assert result["content"] == "content here"
    assert result["metadata"] == {"k": "v"}


def test_get_returns_none_when_not_found():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = None

    result = backend.get("col", "ghost")
    assert result is None


# ── update() ─────────────────────────────────────────────────────────────────


def test_update_issues_update_sql():
    """update() should issue an UPDATE ... WHERE id = %s."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.rowcount = 1

    backend.update("col", "doc-1", "new content", _v(0.5, 0.5), {"v": 2})

    update_call = next(c for c in cur.execute.call_args_list if "UPDATE" in c.args[0])
    sql, params = update_call.args
    assert "UPDATE col" in sql
    assert "doc-1" not in sql  # id must be parameterised
    assert params[-1] == "doc-1"  # id is the last param


def test_update_returns_true_when_row_found():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.rowcount = 1

    result = backend.update("col", "doc-1", "content", _v(1.0), {})
    assert result is True


def test_update_returns_false_when_not_found():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.rowcount = 0

    result = backend.update("col", "ghost", "content", _v(1.0), {})
    assert result is False


def test_update_serialises_metadata():
    """update() must pass metadata as a JSON string parameter."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.rowcount = 1

    backend.update("col", "doc-1", "text", _v(1.0), {"flag": True})

    update_call = next(c for c in cur.execute.call_args_list if "UPDATE" in c.args[0])
    params = update_call.args[1]
    # params: (content, metadata_json, vec_str, id)
    meta_param = params[1]
    assert json.loads(meta_param) == {"flag": True}


# ── delete() ─────────────────────────────────────────────────────────────────


def test_delete_issues_delete_sql():
    """delete() should issue DELETE FROM ... WHERE id = %s."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.rowcount = 1

    backend.delete("col", "doc-1")

    delete_call = next(c for c in cur.execute.call_args_list if "DELETE" in c.args[0])
    sql, params = delete_call.args
    assert "DELETE FROM col" in sql
    assert "doc-1" not in sql
    assert params == ("doc-1",)


def test_delete_returns_true_when_found():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.rowcount = 1

    assert backend.delete("col", "doc-1") is True


def test_delete_returns_false_when_not_found():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.rowcount = 0

    assert backend.delete("col", "ghost") is False


# ── collection_count() ────────────────────────────────────────────────────────


def test_collection_count_issues_count_star():
    """collection_count() should issue SELECT COUNT(*) FROM <table>."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (12,)

    count = backend.collection_count("my_col")

    count_call = next(c for c in cur.execute.call_args_list if "COUNT" in c.args[0])
    sql = count_call.args[0]
    assert "COUNT(*)" in sql
    assert "my_col" in sql
    assert count == 12


def test_collection_count_returns_zero_on_error():
    """collection_count() should return 0 if the table does not exist."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.execute.side_effect = Exception("relation does not exist")

    count = backend.collection_count("missing")
    assert count == 0


# ── collection_peek() ─────────────────────────────────────────────────────────


def test_collection_peek_issues_select_with_limit():
    """collection_peek() should issue SELECT ... LIMIT %s."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [
        ("p1", "peek content", json.dumps({"k": "v"})),
    ]

    result = backend.collection_peek("col", limit=5)

    peek_call = next(c for c in cur.execute.call_args_list if "SELECT" in c.args[0])
    sql, params = peek_call.args
    assert "LIMIT" in sql
    assert params == (5,)


def test_collection_peek_returns_correct_structure():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [
        ("id1", "content one", json.dumps({"a": 1})),
        ("id2", "content two", json.dumps({"b": 2})),
    ]

    result = backend.collection_peek("col")

    assert len(result) == 2
    assert result[0]["id"] == "id1"
    assert result[0]["content"] == "content one"
    assert result[0]["metadata"] == {"a": 1}
    assert "similarity" not in result[0]


def test_collection_peek_returns_empty_on_error():
    """collection_peek() should return [] if the table does not exist."""
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)

    cur = mock_conn.cursor.return_value.__enter__.return_value
    cur.execute.side_effect = Exception("relation does not exist")

    result = backend.collection_peek("no_table")
    assert result == []


# ── SQL injection safety ───────────────────────────────────────────────────────


def test_invalid_collection_name_rejected_in_insert():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)
    with pytest.raises(ValueError):
        backend.insert("bad-name", "id", "text", _v(1.0), {})


def test_invalid_collection_name_rejected_in_search():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)
    with pytest.raises(ValueError):
        backend.search("bad-name", _v(1.0))


def test_invalid_collection_name_rejected_in_delete():
    mock_conn = _make_mock_conn()
    backend = _connected_backend(mock_conn)
    with pytest.raises(ValueError):
        backend.delete_collection("bad-name")
