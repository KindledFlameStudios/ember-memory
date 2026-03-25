"""Engine stats — read-only summary for controller UI and tray."""

from ember_memory.core.engine.state import EngineState


def get_engine_stats(state: EngineState) -> dict:
    """Get summary of engine state for display."""
    all_heat = state.get_all_heat()
    hot_count = sum(1 for h in all_heat.values() if h >= 0.5)

    # Count established connections (strength >= 3.0)
    # We need to query all connections — use a direct SQL query
    conn = state._conn
    total_connections = conn.execute("SELECT COUNT(*) FROM connections").fetchone()[0]
    established = conn.execute(
        "SELECT COUNT(*) FROM connections WHERE strength >= 3.0"
    ).fetchone()[0]

    return {
        "tick_count": state.get_tick(),
        "total_memories_tracked": len(all_heat),
        "hot_memories": hot_count,
        "total_connections": total_connections,
        "established_connections": established,
        "heat_mode": state.get_config("heat_mode", "universal"),
        "ignored_clis": {
            ai_id: state.get_config(f"heat_ignore_{ai_id}", "false") == "true"
            for ai_id in ["claude", "gemini", "codex"]
        },
    }
