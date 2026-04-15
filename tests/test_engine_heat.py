import pytest
from ember_memory.core.engine.state import EngineState
from ember_memory.core.engine.heat import HeatMap

@pytest.fixture
def heat(tmp_path):
    state = EngineState(db_path=str(tmp_path / "engine.db"))
    return HeatMap(state)

def test_record_access_adds_heat(heat):
    heat.record_access("doc1")
    assert heat.get_boost("doc1") > 0.0

def test_multiple_accesses_increase_boost(heat):
    heat.record_access("doc1")
    b1 = heat.get_boost("doc1")
    heat.record_access("doc1")
    b2 = heat.get_boost("doc1")
    assert b2 > b1

def test_tick_decays(heat):
    heat.record_access("doc1")
    b1 = heat.get_boost("doc1")
    heat.tick()
    b2 = heat.get_boost("doc1")
    assert b2 < b1

def test_boost_capped_at_1(heat):
    for _ in range(20):
        heat.record_access("doc1")
    assert heat.get_boost("doc1") <= 1.0

def test_cold_memory_zero(heat):
    assert heat.get_boost("never_accessed") == 0.0

def test_mode_default_universal(heat):
    assert heat.get_mode() == "universal"

def test_mode_switch(heat):
    heat.set_mode("per_cli")
    assert heat.get_mode() == "per_cli"

def test_ignore_default_false(heat):
    assert heat.is_ignored("codex") is False

def test_ignore_toggle(heat):
    heat.set_ignored("codex", True)
    assert heat.is_ignored("codex") is True
    heat.set_ignored("codex", False)
    assert heat.is_ignored("codex") is False

def test_per_cli_isolation(heat):
    heat.set_mode("per_cli")
    heat.record_access("doc1", ai_id="claude")
    assert heat.get_boost("doc1", ai_id="claude") > 0.0
    assert heat.get_boost("doc1", ai_id="gemini") == 0.0
