import pytest
from ember_memory.core.engine.state import EngineState
from ember_memory.core.engine.stats import get_engine_stats

@pytest.fixture
def state(tmp_path):
    return EngineState(db_path=str(tmp_path / "engine.db"))

def test_empty_stats(state):
    stats = get_engine_stats(state)
    assert stats["tick_count"] == 0
    assert stats["total_memories_tracked"] == 0
    assert stats["hot_memories"] == 0
    assert stats["heat_mode"] == "universal"

def test_stats_with_data(state):
    state.increment_heat("doc1", 3.0)
    state.increment_heat("doc2", 0.1)
    state.increment_connection("a", "b", 4.0)
    state.increment_tick()
    stats = get_engine_stats(state)
    assert stats["tick_count"] == 1
    assert stats["total_memories_tracked"] == 2
    assert stats["hot_memories"] == 1  # Only doc1 (3.0 >= 0.5)
    assert stats["established_connections"] == 1
    assert stats["total_connections"] == 1

def test_ignored_clis(state):
    state.set_config("heat_ignore_codex", "true")
    stats = get_engine_stats(state)
    assert stats["ignored_clis"]["codex"] is True
    assert stats["ignored_clis"]["claude"] is False
