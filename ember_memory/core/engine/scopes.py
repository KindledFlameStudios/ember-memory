"""Helpers for mapping Engine scopes back to CLI identities.

Session-scoped heat uses identifiers like ``cc-12345`` or ``codex-<thread>``.
These helpers let the controller and server aggregate that heat back to the
parent CLI, respect ignored AIs, and filter disabled collections consistently.
"""

from __future__ import annotations

import json
import re

from ember_memory.core.engine.state import EngineState

BASE_CLI_IDS: tuple[str, ...] = ("claude", "gemini", "codex")
_LEGACY_CODEX_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f-]{27,}$")


def load_custom_cli_ids(state: EngineState | None) -> list[str]:
    """Return normalized custom CLI ids stored in Engine config."""
    if state is None:
        return []

    try:
        raw = state.get_config("custom_clis", "[]")
        parsed = json.loads(raw)
    except Exception:
        return []

    cli_ids: list[str] = []
    for item in parsed if isinstance(parsed, list) else []:
        if not isinstance(item, dict):
            continue
        cli_id = str(item.get("id") or "").strip().lower()
        if cli_id and cli_id not in cli_ids:
            cli_ids.append(cli_id)
    return cli_ids


def get_all_cli_ids(state: EngineState | None = None) -> list[str]:
    """Return built-in plus custom CLI ids, preserving stable order."""
    ordered = list(BASE_CLI_IDS)
    for cli_id in load_custom_cli_ids(state):
        if cli_id not in ordered:
            ordered.append(cli_id)
    return ordered


def scope_to_cli(scope: str | None, cli_ids: list[str] | tuple[str, ...] | None = None) -> str | None:
    """Map a stored Engine heat scope back to its parent CLI id."""
    raw = str(scope or "").strip().lower()
    if not raw:
        return None

    if raw.startswith("cc-") or raw.startswith("claude"):
        return "claude"
    if raw.startswith("gemini"):
        return "gemini"
    if raw.startswith("codex"):
        return "codex"
    if _LEGACY_CODEX_UUID.match(raw):
        return "codex"

    for cli_id in cli_ids or ():
        cli_id = str(cli_id or "").strip().lower()
        if cli_id and (raw == cli_id or raw.startswith(f"{cli_id}-") or raw.startswith(f"{cli_id}_")):
            return cli_id
    return None


def matching_heat_scopes(state: EngineState, ai_id: str) -> list[str]:
    """Return all stored heat scopes that belong to the given CLI."""
    target = str(ai_id or "").strip().lower()
    if not target:
        return []

    cli_ids = get_all_cli_ids(state)
    scopes = {target}
    rows = state._conn.execute("SELECT DISTINCT ai_id FROM heat_map").fetchall()
    for row in rows:
        scope = str(row["ai_id"] or "").strip()
        if not scope:
            continue
        if scope.lower() == target or scope_to_cli(scope, cli_ids=cli_ids) == target:
            scopes.add(scope)
    return sorted(scopes)


def get_disabled_collections(state: EngineState) -> set[str]:
    """Return collection names currently disabled in controller config."""
    rows = state._conn.execute(
        "SELECT key, value FROM config WHERE key LIKE 'collection_disabled_%'"
    ).fetchall()
    disabled = set()
    for row in rows:
        if row["value"] == "true":
            disabled.add(row["key"].replace("collection_disabled_", "", 1))
    return disabled


def aggregate_heat_by_memory(state: EngineState, ai_id: str | None = None) -> dict[str, float]:
    """Aggregate heat by memory id, respecting session scopes and disabled state."""
    selected = str(ai_id or "").strip().lower() or None
    cli_ids = get_all_cli_ids(state)
    disabled_collections = get_disabled_collections(state)
    memory_meta = state.get_all_memory_meta()
    ignored = {
        cli_id
        for cli_id in cli_ids
        if state.get_config(f"heat_ignore_{cli_id}", "false") == "true"
    }

    rows = state._conn.execute(
        "SELECT ai_id, memory_id, heat FROM heat_map WHERE heat > 0.01"
    ).fetchall()

    merged: dict[str, float] = {}
    for row in rows:
        scope = str(row["ai_id"] or "").strip()
        memory_id = row["memory_id"]
        heat = float(row["heat"])
        collection = (memory_meta.get(memory_id) or {}).get("collection", "")
        if collection and collection in disabled_collections:
            continue

        parent_cli = scope_to_cli(scope, cli_ids=cli_ids) if scope else None
        if parent_cli and parent_cli in ignored:
            continue

        if selected is not None and scope.lower() != selected and parent_cli != selected:
            continue

        merged[memory_id] = merged.get(memory_id, 0.0) + heat

    return merged
