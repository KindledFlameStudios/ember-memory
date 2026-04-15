import pytest
from unittest.mock import MagicMock
from ember_memory.core.search import retrieve, RetrievalResult


def _mock_backend(collections, search_results):
    backend = MagicMock()
    backend.list_collections.return_value = [{"name": n, "count": 5} for n in collections]
    backend.search.return_value = search_results
    return backend


def _mock_embedder(dim=4):
    embedder = MagicMock()
    embedder.embed.return_value = [0.1] * dim
    embedder.dimension.return_value = dim
    return embedder


def test_returns_retrieval_results():
    backend = _mock_backend(["notes"], [
        {"id": "d1", "content": "hello", "metadata": {"tag": "test"}, "similarity": 0.8},
    ])
    results = retrieve("test", ai_id="claude", backend=backend, embedder=_mock_embedder())
    assert len(results) == 1
    assert isinstance(results[0], RetrievalResult)
    assert results[0].content == "hello"
    assert results[0].similarity == 0.8
    assert results[0].composite_score == 0.8  # No engine yet


def test_filters_by_namespace():
    backend = _mock_backend(
        ["shared--notes", "claude--prefs", "gemini--prefs"],
        [{"id": "d1", "content": "x", "metadata": {}, "similarity": 0.9}],
    )
    retrieve("query", ai_id="claude", backend=backend, embedder=_mock_embedder())
    searched = [call.kwargs.get("collection", call.args[0] if call.args else None)
                for call in backend.search.call_args_list]
    assert "shared--notes" in searched
    assert "claude--prefs" in searched
    assert "gemini--prefs" not in searched


def test_filters_below_threshold():
    backend = _mock_backend(["notes"], [
        {"id": "d1", "content": "relevant", "metadata": {}, "similarity": 0.8},
        {"id": "d2", "content": "irrelevant", "metadata": {}, "similarity": 0.1},
    ])
    results = retrieve("query", ai_id="claude", backend=backend,
                       embedder=_mock_embedder(), similarity_threshold=0.35)
    assert len(results) == 1
    assert results[0].id == "d1"


def test_respects_limit():
    backend = _mock_backend(["notes"], [
        {"id": f"d{i}", "content": f"text {i}", "metadata": {}, "similarity": 0.9 - i * 0.05}
        for i in range(10)
    ])
    results = retrieve("query", ai_id="claude", backend=backend,
                       embedder=_mock_embedder(), limit=3)
    assert len(results) <= 3


def test_sorts_by_composite_score():
    backend = _mock_backend(["notes"], [
        {"id": "low", "content": "low", "metadata": {}, "similarity": 0.5},
        {"id": "high", "content": "high", "metadata": {}, "similarity": 0.9},
        {"id": "mid", "content": "mid", "metadata": {}, "similarity": 0.7},
    ])
    results = retrieve("query", ai_id="claude", backend=backend, embedder=_mock_embedder())
    assert results[0].id == "high"
    assert results[1].id == "mid"
    assert results[2].id == "low"


def test_empty_on_no_collections():
    backend = _mock_backend([], [])
    results = retrieve("query", ai_id="claude", backend=backend, embedder=_mock_embedder())
    assert results == []


def test_empty_on_no_backend():
    results = retrieve("query", ai_id="claude", backend=None, embedder=None)
    assert results == []


def test_skips_empty_collections():
    backend = MagicMock()
    backend.list_collections.return_value = [
        {"name": "full", "count": 5},
        {"name": "empty", "count": 0},
    ]
    backend.search.return_value = [
        {"id": "d1", "content": "x", "metadata": {}, "similarity": 0.8},
    ]
    results = retrieve("query", ai_id="claude", backend=backend, embedder=_mock_embedder())
    # Should only search "full", not "empty"
    assert backend.search.call_count == 1


def test_handles_search_error_gracefully():
    backend = _mock_backend(["notes", "broken"], [])
    backend.search.side_effect = [
        [{"id": "d1", "content": "ok", "metadata": {}, "similarity": 0.8}],
        Exception("backend error"),
    ]
    results = retrieve("query", ai_id="claude", backend=backend, embedder=_mock_embedder())
    assert len(results) == 1  # Got results from "notes", skipped "broken"


def test_handles_embedding_error_gracefully():
    backend = _mock_backend(["notes"], [])
    embedder = _mock_embedder()
    embedder.embed.side_effect = Exception("ollama down")
    results = retrieve("query", ai_id="claude", backend=backend, embedder=embedder)
    assert results == []


def test_merges_across_collections():
    backend = MagicMock()
    backend.list_collections.return_value = [
        {"name": "arch", "count": 5},
        {"name": "debug", "count": 5},
    ]
    backend.search.side_effect = [
        [{"id": "a1", "content": "arch stuff", "metadata": {}, "similarity": 0.7}],
        [{"id": "d1", "content": "debug stuff", "metadata": {}, "similarity": 0.9}],
    ]
    results = retrieve("query", ai_id="claude", backend=backend, embedder=_mock_embedder())
    assert len(results) == 2
    assert results[0].id == "d1"  # Higher similarity first
    assert results[0].collection == "debug"
    assert results[1].collection == "arch"
