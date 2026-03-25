"""
Tests for ember_memory.core.engine.state.EngineState.

Each test uses an isolated in-tmp-path SQLite DB via the `state` fixture.
"""

import pytest
from ember_memory.core.engine.state import EngineState


@pytest.fixture
def state(tmp_path):
    return EngineState(db_path=str(tmp_path / "engine.db"))


# ── Ticks ────────────────────────────────────────────────────────────────────


def test_tick_default_zero(state):
    assert state.get_tick() == 0


def test_tick_increment_once(state):
    result = state.increment_tick()
    assert result == 1
    assert state.get_tick() == 1


def test_tick_increment_twice(state):
    state.increment_tick()
    result = state.increment_tick()
    assert result == 2
    assert state.get_tick() == 2


# ── Heat Map ─────────────────────────────────────────────────────────────────


def test_heat_default_zero(state):
    assert state.get_heat("mem-001") == 0.0


def test_heat_set_and_get(state):
    state.set_heat("mem-001", 3.5)
    assert state.get_heat("mem-001") == pytest.approx(3.5)


def test_heat_increment(state):
    state.increment_heat("mem-001", 2.0)
    state.increment_heat("mem-001", 1.5)
    assert state.get_heat("mem-001") == pytest.approx(3.5)


def test_heat_increment_default_amount(state):
    state.increment_heat("mem-001")
    state.increment_heat("mem-001")
    assert state.get_heat("mem-001") == pytest.approx(2.0)


def test_heat_decay_math(state):
    state.set_heat("mem-001", 4.0)
    state.set_heat("mem-002", 2.0)
    state.decay_all_heat(factor=0.5)
    assert state.get_heat("mem-001") == pytest.approx(2.0)
    assert state.get_heat("mem-002") == pytest.approx(1.0)


def test_heat_decay_removes_near_zero(state):
    state.set_heat("mem-small", 0.005)
    state.set_heat("mem-big", 5.0)
    state.decay_all_heat(factor=0.95)
    # mem-small: 0.005 * 0.95 = 0.00475 → below 0.01, removed
    assert state.get_heat("mem-small") == 0.0
    # mem-big: 5.0 * 0.95 = 4.75 → survives
    assert state.get_heat("mem-big") == pytest.approx(4.75)


def test_heat_ai_id_scoped(state):
    state.set_heat("mem-001", 1.0, ai_id="claude")
    state.set_heat("mem-001", 9.0, ai_id="gpt")
    assert state.get_heat("mem-001", ai_id="claude") == pytest.approx(1.0)
    assert state.get_heat("mem-001", ai_id="gpt") == pytest.approx(9.0)
    assert state.get_heat("mem-001") == 0.0  # global scope untouched


def test_heat_decay_ai_id_scoped(state):
    state.set_heat("mem-a", 2.0, ai_id="claude")
    state.set_heat("mem-a", 2.0, ai_id="gpt")
    state.decay_all_heat(factor=0.5, ai_id="claude")
    assert state.get_heat("mem-a", ai_id="claude") == pytest.approx(1.0)
    assert state.get_heat("mem-a", ai_id="gpt") == pytest.approx(2.0)


def test_get_all_heat(state):
    state.set_heat("mem-001", 1.0)
    state.set_heat("mem-002", 2.0)
    result = state.get_all_heat()
    assert result == {"mem-001": pytest.approx(1.0), "mem-002": pytest.approx(2.0)}


def test_get_all_heat_empty(state):
    assert state.get_all_heat() == {}


# ── Connections ──────────────────────────────────────────────────────────────


def test_connection_default_zero(state):
    assert state.get_connection("a", "b") == 0.0


def test_connection_symmetric(state):
    state.increment_connection("a", "b", 3.0)
    assert state.get_connection("a", "b") == pytest.approx(3.0)
    assert state.get_connection("b", "a") == pytest.approx(3.0)


def test_connection_accumulate(state):
    state.increment_connection("x", "y", 1.5)
    state.increment_connection("y", "x", 2.5)  # symmetric — same row
    assert state.get_connection("x", "y") == pytest.approx(4.0)


def test_connection_default_amount(state):
    state.increment_connection("a", "b")
    state.increment_connection("a", "b")
    assert state.get_connection("a", "b") == pytest.approx(2.0)


def test_connection_first_seen_set_on_insert(state):
    state.increment_connection("a", "b", 1.0)
    from ember_memory.core.engine.state import _normalize_pair
    import sqlite3
    conn = sqlite3.connect(str(state.db_path))
    conn.row_factory = sqlite3.Row
    na, nb = _normalize_pair("a", "b")
    row = conn.execute(
        "SELECT first_seen, last_seen FROM connections WHERE id_a=? AND id_b=?",
        (na, nb),
    ).fetchone()
    assert row["first_seen"] is not None
    assert row["last_seen"] is not None


def test_connection_last_seen_updates(state):
    import time
    import sqlite3
    from ember_memory.core.engine.state import _normalize_pair

    state.increment_connection("a", "b", 1.0)
    time.sleep(0.01)
    state.increment_connection("a", "b", 1.0)

    conn = sqlite3.connect(str(state.db_path))
    conn.row_factory = sqlite3.Row
    na, nb = _normalize_pair("a", "b")
    row = conn.execute(
        "SELECT first_seen, last_seen FROM connections WHERE id_a=? AND id_b=?",
        (na, nb),
    ).fetchone()
    # last_seen should be >= first_seen
    assert row["last_seen"] >= row["first_seen"]


def test_connection_decay(state):
    state.increment_connection("a", "b", 4.0)
    state.decay_all_connections(factor=0.5)
    assert state.get_connection("a", "b") == pytest.approx(2.0)


def test_connection_decay_removes_near_zero(state):
    state.increment_connection("a", "b", 0.005)
    state.increment_connection("x", "y", 5.0)
    state.decay_all_connections(factor=0.95)
    # a-b: 0.005 * 0.95 = 0.00475 → below 0.01, removed
    assert state.get_connection("a", "b") == 0.0
    # x-y: 5.0 * 0.95 = 4.75 → survives
    assert state.get_connection("x", "y") == pytest.approx(4.75)


def test_get_connections_for(state):
    state.increment_connection("center", "neighbor-1", 3.0)
    state.increment_connection("center", "neighbor-2", 1.5)
    state.increment_connection("unrelated-a", "unrelated-b", 9.0)

    results = state.get_connections_for("center")
    ids = {r["id"] for r in results}
    assert ids == {"neighbor-1", "neighbor-2"}
    strengths = {r["id"]: r["strength"] for r in results}
    assert strengths["neighbor-1"] == pytest.approx(3.0)
    assert strengths["neighbor-2"] == pytest.approx(1.5)


def test_get_connections_for_empty(state):
    assert state.get_connections_for("nobody") == []


def test_get_connections_for_both_directions(state):
    """Connections where memory_id is id_b should still appear."""
    state.increment_connection("alpha", "beta", 2.0)
    results = state.get_connections_for("beta")
    assert len(results) == 1
    assert results[0]["id"] == "alpha"
    assert results[0]["strength"] == pytest.approx(2.0)


# ── Last Accessed ─────────────────────────────────────────────────────────────


def test_last_accessed_default_none(state):
    assert state.get_last_accessed("mem-new") is None


def test_last_accessed_update_sets_timestamp(state):
    state.update_last_accessed("mem-001")
    ts = state.get_last_accessed("mem-001")
    assert ts is not None
    assert "T" in ts  # ISO format sanity check


def test_last_accessed_update_changes_timestamp(state):
    import time
    state.update_last_accessed("mem-001")
    ts1 = state.get_last_accessed("mem-001")
    time.sleep(0.01)
    state.update_last_accessed("mem-001")
    ts2 = state.get_last_accessed("mem-001")
    assert ts2 >= ts1
    # Should be a different (or at minimum equal) timestamp
    assert ts2 is not None


# ── Config ────────────────────────────────────────────────────────────────────


def test_config_default_value(state):
    assert state.get_config("missing_key") == ""
    assert state.get_config("missing_key", default="fallback") == "fallback"


def test_config_set_and_get(state):
    state.set_config("heat_mode", "per_cli")
    assert state.get_config("heat_mode") == "per_cli"


def test_config_overwrite(state):
    state.set_config("mode", "global")
    state.set_config("mode", "per_cli")
    assert state.get_config("mode") == "per_cli"


def test_config_multiple_keys(state):
    state.set_config("key_a", "value_a")
    state.set_config("key_b", "value_b")
    assert state.get_config("key_a") == "value_a"
    assert state.get_config("key_b") == "value_b"
