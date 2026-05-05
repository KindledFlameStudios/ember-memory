from ember_memory.core.engine.scopes import (
    aggregate_heat_by_memory,
    matching_heat_scopes,
    scope_to_cli,
)
from ember_memory.core.engine.state import EngineState


def test_scope_to_cli_maps_built_in_and_custom_scopes():
    cli_ids = ["claude", "gemini", "codex", "openclaw"]

    assert scope_to_cli("cc-12345", cli_ids=cli_ids) == "claude"
    assert scope_to_cli("codex-thread-1", cli_ids=cli_ids) == "codex"
    assert scope_to_cli("openclaw-session-7", cli_ids=cli_ids) == "openclaw"


def test_matching_heat_scopes_includes_session_scopes(tmp_path):
    state = EngineState(db_path=str(tmp_path / "engine.db"))
    state.set_heat("doc1", 1.0, ai_id="codex")
    state.set_heat("doc1", 2.0, ai_id="codex-thread-1")
    state.set_heat("doc1", 3.0, ai_id="codex-thread-2")

    scopes = matching_heat_scopes(state, "codex")

    assert "codex" in scopes
    assert "codex-thread-1" in scopes
    assert "codex-thread-2" in scopes


def test_aggregate_heat_merges_session_scopes_for_cli(tmp_path):
    state = EngineState(db_path=str(tmp_path / "engine.db"))
    state.set_heat("doc1", 1.25, ai_id="codex-thread-1")
    state.set_heat("doc1", 0.75, ai_id="codex-thread-2")
    state.set_heat("doc2", 2.0, ai_id="gemini-1")

    assert aggregate_heat_by_memory(state, ai_id="codex") == {"doc1": 2.0}


def test_aggregate_heat_filters_disabled_collections(tmp_path):
    state = EngineState(db_path=str(tmp_path / "engine.db"))
    state.set_heat("doc1", 2.0, ai_id="codex-thread-1")
    state.upsert_memory_meta("doc1", "archive", "Archive notes")
    state.set_config("collection_disabled_archive", "true")

    assert aggregate_heat_by_memory(state, ai_id="codex") == {}
