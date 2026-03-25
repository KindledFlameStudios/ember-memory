import pytest
from ember_memory.core.engine.state import EngineState
from ember_memory.core.engine.connections import ConnectionGraph

@pytest.fixture
def graph(tmp_path):
    state = EngineState(db_path=str(tmp_path / "engine.db"))
    return ConnectionGraph(state)

def test_co_occurrence_creates_connections(graph):
    graph.record_co_occurrence(["a", "b", "c"])
    # Should create a-b, a-c, b-c connections
    assert graph._state.get_connection("a", "b") > 0
    assert graph._state.get_connection("a", "c") > 0
    assert graph._state.get_connection("b", "c") > 0

def test_bonus_zero_without_connections(graph):
    assert graph.get_bonus("doc1", ["doc2", "doc3"]) == 0.0

def test_bonus_increases_with_strength(graph):
    graph.record_co_occurrence(["a", "b"])
    b1 = graph.get_bonus("a", ["b"])
    graph.record_co_occurrence(["a", "b"])
    b2 = graph.get_bonus("a", ["b"])
    assert b2 > b1

def test_bonus_capped_at_1(graph):
    for _ in range(20):
        graph.record_co_occurrence(["a", "b"])
    assert graph.get_bonus("a", ["b"]) <= 1.0

def test_bonus_with_empty_context(graph):
    assert graph.get_bonus("a", []) == 0.0

def test_tick_decays_connections(graph):
    graph.record_co_occurrence(["a", "b"])
    s1 = graph._state.get_connection("a", "b")
    graph.tick()
    s2 = graph._state.get_connection("a", "b")
    assert s2 < s1

def test_established_threshold(graph):
    for _ in range(4):
        graph.record_co_occurrence(["a", "b"])
    established = graph.get_established("a")
    assert len(established) >= 1
    assert established[0]["id"] == "b"

def test_not_established_below_threshold(graph):
    graph.record_co_occurrence(["a", "b"])
    established = graph.get_established("a")
    assert len(established) == 0

def test_single_memory_no_pairs(graph):
    graph.record_co_occurrence(["a"])
    # Single memory = no pairs to connect
    assert graph.get_bonus("a", []) == 0.0
