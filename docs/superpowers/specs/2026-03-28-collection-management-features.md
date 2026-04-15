# Ember Memory — Collection Management Features Spec

**Date:** 2026-03-28
**Authors:** Justin & Kael
**Status:** Approved, ready for implementation

## Feature 1: Renamable Collection Labels

**Problem:** Collections show raw names like `claude--reflections`. Users want friendly labels like "Kael's Reflections."

**Solution:** Store display labels in Engine config table.

**Backend:**
- `EngineState.set_config(f"collection_label_{col_name}", "Kael's Reflections")`
- `EngineState.get_config(f"collection_label_{col_name}", default=col_name)`
- New `EmberAPI.rename_collection_label(col_name, new_label)` method

**UI:**
- Double-click or pencil icon on collection name to edit inline
- Save on Enter/blur, cancel on Escape
- Label stored in engine config, actual collection name unchanged
- Owner section headers also renamable: `ownerLabels` stored in config

**Scope:** Small — config storage exists, UI needs inline edit.

## Feature 2: Enable/Disable Collections

**Problem:** Flameborn lore shouldn't surface during deep dev work. Dev collections shouldn't clutter creative sessions.

**Solution:** Toggle collections active/inactive. Inactive collections skipped during retrieval.

**Backend:**
- `EngineState.set_config(f"collection_disabled_{col_name}", "true")`
- `retrieve()` in `search.py` filters out disabled collections before searching
- New `EmberAPI.toggle_collection(col_name)` → returns new enabled/disabled state

**UI:**
- Toggle switch per collection in the Collections tab (green = active, gray = disabled)
- Disabled collections visually dimmed but still visible
- Bulk toggle: "Enable All" / "Disable All" per owner section

**retrieve() change:**
```python
# After namespace filtering, before searching:
disabled = set()
if engine_db_path:
    engine = _get_engine(engine_db_path)
    if engine:
        state = engine[0]
        disabled = {name for name in visible
                    if state.get_config(f"collection_disabled_{name}", "false") == "true"}
visible = [v for v in visible if v not in disabled]
```

**Scope:** Medium — backend is trivial, UI toggle + visual state needs care.

## Feature 3: Session-Aware Workspaces

**Problem:** Two CC instances share the same ember-memory. Working on Embercore in one and freelancing in another — both get all memories. Need per-session context filtering.

**Solution:** Named workspaces that define which collections are active. Each CLI session can select a workspace.

**Data model:**
```json
// Stored in engine config as JSON
{
  "workspaces": {
    "embercore-dev": {
      "label": "Embercore Dev",
      "collections": {
        "embercore": true,
        "claude--identity": true,
        "claude--reflections": true,
        "flameborn": false,
        "echobound": false
      }
    },
    "creative": {
      "label": "Creative Work",
      "collections": {
        "flameborn": true,
        "echobound": true,
        "claude--identity": true,
        "embercore": false,
        "kfs-roadmap": false
      }
    }
  },
  "session_workspace": {
    "cc-123456": "embercore-dev",
    "cc-789012": "creative"
  }
}
```

**How it works:**
1. Hook passes session ID + workspace env var: `EMBER_WORKSPACE=embercore-dev`
2. `retrieve()` loads workspace config, filters collections by workspace's enabled set
3. If no workspace set, all collections are active (backward compatible)

**UI:**
- Workspaces panel in Settings tab
- Create workspace: name + checkboxes per collection
- Active workspace shown in dashboard header
- Tray menu: switch workspace quickly
- Auto-detect option: map working directory to workspace (if in ~/Embercore/ → embercore-dev)

**Session detection:**
- `EMBER_WORKSPACE` env var (explicit, highest priority)
- Working directory auto-mapping (configurable in workspace config)
- Default: no workspace = all collections active

**Scope:** Large — needs workspace CRUD, session mapping, UI panel, tray integration, retrieve() filtering.

## Implementation Order

1. Feature 2 (enable/disable) — foundational, Feature 3 builds on it
2. Feature 1 (renamable labels) — independent, quick win
3. Feature 3 (workspaces) — builds on Feature 2's collection filtering

## Notes

- All state stored in Engine SQLite — no new files or config formats needed
- Backward compatible — no workspace = all collections active, no labels = show raw names
- Owner section headers ("Kael's Collections") already configurable in `ownerLabels` JS object
