"""Integration tests: retrieve() with Ember Engine active.

Uses a real EngineState (SQLite in tmp_path) and a mock backend/embedder
so tests are fast and hermetic -- no ChromaDB, no Ollama required.
"""

import pytest
import os
from unittest.mock import MagicMock
from ember_memory.core.search import retrieve, RetrievalResult, _engine_cache
from ember_memory.core.engine.state import EngineState
from ember_memory.core.engine.heat import HeatMap


# -- Fixtures -----------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_engine_cache():
    """Wipe the module-level engine cache between tests so each test gets a
    fresh Engine instance against its own tmp_path DB."""
    _engine_cache.clear()
    yield
    _engine_cache.clear()


@pytest.fixture
def engine_dir(tmp_path):
    d = tmp_path / "engine"
    d.mkdir()
    return str(d)


# -- Helpers ------------------------------------------------------------------

def _mock_backend(collections, search_results):
    backend = MagicMock()
    backend.list_collections.return_value = [{"name": n, "count": 5} for n in collections]
    backend.search.return_value = search_results
    return backend


def _mock_embedder():
    e = MagicMock()
    e.embed.return_value = [0.1] * 4
    return e


# -- Tests --------------------------------------------------------------------

def test_engine_boosts_hot_memory(engine_dir):
    """A pre-heated memory should score higher than a cold one with same similarity."""
    db_path = os.path.join(engine_dir, "engine.db")

    # Pre-heat doc1 using the real EngineState + HeatMap
    state = EngineState(db_path=db_path)
    heat = HeatMap(state)
    for _ in range(5):
        heat.record_access("hot_doc")

    backend = _mock_backend(["notes"], [
        {"id": "hot_doc", "content": "hot", "metadata": {}, "similarity": 0.7},
        {"id": "cold_doc", "content": "cold", "metadata": {}, "similarity": 0.7},
    ])

    results = retrieve(
        "query",
        ai_id="claude",
        backend=backend,
        embedder=_mock_embedder(),
        engine_db_path=db_path,
    )

    # hot_doc should rank above cold_doc despite equal similarity
    assert len(results) == 2
    assert results[0].id == "hot_doc"
    assert results[0].composite_score > results[1].composite_score


def test_retrieve_without_engine_still_works():
    """If no engine_db_path, composite_score == similarity (backward compat)."""
    backend = _mock_backend(["notes"], [
        {"id": "d1", "content": "hello", "metadata": {}, "similarity": 0.8},
    ])
    results = retrieve("query", ai_id="claude", backend=backend, embedder=_mock_embedder())
    assert len(results) == 1
    assert results[0].composite_score == results[0].similarity


def test_engine_records_access_after_retrieval(engine_dir):
    """After retrieval, accessed memories should have heat > 0 and a last_accessed timestamp."""
    db_path = os.path.join(engine_dir, "engine.db")
    backend = _mock_backend(["notes"], [
        {"id": "doc1", "content": "x", "metadata": {}, "similarity": 0.8},
    ])
    retrieve(
        "query",
        ai_id="claude",
        backend=backend,
        embedder=_mock_embedder(),
        engine_db_path=db_path,
    )

    # Inspect state directly (fresh EngineState, same DB file)
    state = EngineState(db_path=db_path)
    assert state.get_heat("doc1") > 0.0
    assert state.get_last_accessed("doc1") is not None


def test_engine_records_co_occurrence(engine_dir):
    """Two memories returned together should gain a connection."""
    db_path = os.path.join(engine_dir, "engine.db")
    backend = _mock_backend(["notes"], [
        {"id": "a", "content": "alpha", "metadata": {}, "similarity": 0.8},
        {"id": "b", "content": "beta", "metadata": {}, "similarity": 0.75},
    ])
    retrieve(
        "query",
        ai_id="claude",
        backend=backend,
        embedder=_mock_embedder(),
        engine_db_path=db_path,
    )

    state = EngineState(db_path=db_path)
    assert state.get_connection("a", "b") > 0.0


def test_engine_ignored_ai_gets_no_heat_boost(engine_dir):
    """An ignored ai_id should not receive a heat boost (boost forced to 0)."""
    db_path = os.path.join(engine_dir, "engine.db")

    # Pre-heat under the "ignored" ai
    state = EngineState(db_path=db_path)
    heat = HeatMap(state)
    for _ in range(5):
        heat.record_access("doc1", ai_id="ignored_ai")
    heat.set_ignored("ignored_ai", True)

    backend = _mock_backend(["notes"], [
        {"id": "doc1", "content": "x", "metadata": {}, "similarity": 0.7},
        {"id": "doc2", "content": "y", "metadata": {}, "similarity": 0.7},
    ])

    results = retrieve(
        "query",
        ai_id="ignored_ai",
        backend=backend,
        embedder=_mock_embedder(),
        engine_db_path=db_path,
    )

    # Both should score the same because heat boost is suppressed for ignored_ai
    assert len(results) == 2
    assert results[0].composite_score == results[1].composite_score


def test_engine_creates_directory_if_missing(tmp_path):
    """Engine should create the engine/ subdirectory automatically."""
    db_path = str(tmp_path / "auto_created" / "engine.db")
    # Directory does NOT exist yet

    backend = _mock_backend(["notes"], [
        {"id": "d1", "content": "text", "metadata": {}, "similarity": 0.8},
    ])
    results = retrieve(
        "query",
        ai_id="claude",
        backend=backend,
        embedder=_mock_embedder(),
        engine_db_path=db_path,
    )
    assert len(results) == 1
    assert os.path.exists(db_path)


def test_engine_failure_falls_back_gracefully():
    """If the engine DB path is unwritable, retrieval still works with similarity scoring."""
    bad_db_path = "/root/no_permission_here/engine.db"

    backend = _mock_backend(["notes"], [
        {"id": "d1", "content": "hello", "metadata": {}, "similarity": 0.8},
    ])
    # Should not raise -- falls back to similarity scoring
    results = retrieve(
        "query",
        ai_id="claude",
        backend=backend,
        embedder=_mock_embedder(),
        engine_db_path=bad_db_path,
    )
    assert len(results) == 1
    assert results[0].composite_score == results[0].similarity


def test_engine_tick_increments_on_each_retrieval(engine_dir):
    """Each retrieve() call should increment the engine tick counter."""
    db_path = os.path.join(engine_dir, "engine.db")
    backend = _mock_backend(["notes"], [
        {"id": "d1", "content": "x", "metadata": {}, "similarity": 0.8},
    ])

    retrieve("q1", ai_id="claude", backend=backend,
             embedder=_mock_embedder(), engine_db_path=db_path)
    retrieve("q2", ai_id="claude", backend=backend,
             embedder=_mock_embedder(), engine_db_path=db_path)

    state = EngineState(db_path=db_path)
    assert state.get_tick() == 2
