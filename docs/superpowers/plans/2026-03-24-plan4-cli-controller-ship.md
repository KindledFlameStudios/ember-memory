# Ember Memory v2.0 — Plan 4: CLI Integrations + Controller + Ship

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire ember-memory into Gemini CLI and Codex, refactor the desktop controller into a full RAG management app with system tray, update the README for multi-CLI launch positioning, and ship v2.0.

**Architecture:** Each CLI integration is a thin adapter (~50-100 lines) wrapping the shared `core.search.retrieve()`. The controller evolves from setup wizard to full management desktop app. System tray provides quick access to heat mode controls.

**Tech Stack:** Python 3.10+, pywebview, pystray, Pillow (tray icon), pytest

**Depends on:** Plans 1 (core), 2 (backends), and 3 (engine)

**Spec:** `docs/superpowers/specs/2026-03-24-ember-memory-v2-design.md`

---

### Task 1: Gemini CLI Integration Research

**Files:**
- Create: `integrations/gemini_cli/RESEARCH.md` (findings)

This is research-first. We need to validate Gemini CLI's hook system before building.

- [ ] **Step 1: Research Gemini CLI extension/hook system**

Find documentation for:
- What hook events are available (equivalent to Claude Code's UserPromptSubmit)
- How hook input is formatted (JSON schema)
- How hook output is injected into context (stdout? return value?)
- Where extension configs live
- What version of Gemini CLI supports hooks

Check: `geminicli.com/docs`, GitHub `google/gemini-cli`, any extension examples.

- [ ] **Step 2: Document findings in RESEARCH.md**

Record: hook event name, input format, output injection method, config location, CLI version tested, and whether MCP-only fallback is needed.

- [ ] **Step 3: Commit research**

---

### Task 2: Gemini CLI Hook Implementation

**Files:**
- Create: `integrations/gemini_cli/hook.py`
- Create: `integrations/gemini_cli/config files` (per research)
- Test: `tests/test_gemini_hook.py`

Based on Task 1 research. If no viable hook exists, implement MCP-only integration.

- [ ] **Step 1: Write the failing test**

Test that hook parses Gemini CLI input format, calls retrieve() with ai_id="gemini", formats output correctly.

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement hook**

Thin wrapper: parse Gemini's input format -> call `retrieve(prompt, ai_id="gemini")` -> format as Gemini's expected output.

- [ ] **Step 4: Create config files for Gemini CLI registration**
- [ ] **Step 5: Run tests, verify pass**
- [ ] **Step 6: Commit**

---

### Task 3: Codex Integration Research

**Files:**
- Create: `integrations/codex/RESEARCH.md`

Same research-first approach for OpenAI's Codex CLI.

- [ ] **Step 1: Research Codex hook/extension system**

Check: OpenAI Codex CLI docs, GitHub, MCP support, session hook API.

Consider: Codex has built-in MEMORY.md via consolidation sub-agent. Our integration might need to work alongside that, not replace it.

- [ ] **Step 2: Document findings**
- [ ] **Step 3: Commit research**

---

### Task 4: Codex Hook Implementation

**Files:**
- Create: `integrations/codex/hook.py`
- Create: `integrations/codex/config files` (per research)
- Test: `tests/test_codex_hook.py`

- [ ] **Step 1-6: Same pattern as Task 2** (test, implement, config, commit)

---

### Task 5: Refactor Claude Code Integration

**Files:**
- Move/update: `integrations/claude_code/hook.py` (from existing hook.py)
- Update: `integrations/claude_code/plugin.json`
- Update: `integrations/claude_code/hooks.json`
- Update: `integrations/claude_code/.mcp.json`

- [ ] **Step 1: Move existing hook.py into integrations/claude_code/**

The hook already works from Plan 1. This is a structural move to match the multi-CLI directory layout.

- [ ] **Step 2: Update plugin.json paths**

Ensure the Claude Code plugin manifest points to the new location.

- [ ] **Step 3: Maintain backward compatibility**

Keep `.claude-plugin/` as redirect for existing installs.

- [ ] **Step 4: Test the hook still works from the new location**
- [ ] **Step 5: Commit**

---

### Task 6: Embedding Factory + Backend Loader (Plan 1 Task 5 + wiring)

**Files:**
- Create: `ember_memory/core/embeddings/loader.py`
- Update: `ember_memory/core/backends/loader.py`

- [ ] **Step 1: Write tests for embedding factory**

Test: returns correct provider for "ollama", "openai", "google". Raises for unknown.

- [ ] **Step 2: Implement embedding factory**

Resolve provider name to class, pass config values as defaults.

- [ ] **Step 3: Update backend factory with all backends from Plan 2**

Add lazy imports for all 8 backends.

- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

---

### Task 7: Controller Refactor (Desktop App)

**Files:**
- Create: `controller/app.py` (refactored from setup_wizard.py)
- Update: `controller/ui.html` (extended from existing ui.html)

- [ ] **Step 1: Create controller directory**

```bash
mkdir -p controller
```

- [ ] **Step 2: Refactor setup_wizard.py into controller/app.py**

Preserve existing EmberAPI class and config I/O. Add new panels:
- Engine dashboard (heat map, connections, decay status)
- Backend settings (switch backend with migration)
- CLI status (which CLIs detected/connected)
- Heat mode controls

- [ ] **Step 3: Update ui.html with new panels**

Add tabs/sections for:
- Engine Dashboard (heat visualization, top hot memories, active connections)
- Settings (embedding provider, backend, heat mode)
- CLI Status (connected CLIs, hook health)

- [ ] **Step 4: Test manually — launch controller, verify all panels render**
- [ ] **Step 5: Commit**

---

### Task 8: System Tray

**Files:**
- Create: `controller/tray.py`
- Update: `requirements.txt` — add pystray, Pillow

- [ ] **Step 1: Implement system tray**

```python
# controller/tray.py
"""System tray icon for Ember Memory — quick access to heat controls."""

import pystray
from PIL import Image
from ember_memory.core.engine.state import EngineState
from ember_memory import config

def create_tray():
    # Load ember icon (or generate a simple one)
    icon_path = os.path.join(os.path.dirname(__file__), "..", "icons", "ember-tray.png")
    if os.path.exists(icon_path):
        image = Image.open(icon_path)
    else:
        # Generate a simple orange circle
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        # ... draw ember icon

    state = EngineState(db_path=os.path.join(config.DATA_DIR, "engine", "engine.db"))

    def get_heat_mode(item):
        return state.get_config("heat_mode", "universal")

    def set_universal(icon, item):
        state.set_config("heat_mode", "universal")

    def set_per_cli(icon, item):
        state.set_config("heat_mode", "per-cli")

    def toggle_ignore(ai_id):
        def handler(icon, item):
            current = state.get_config(f"heat_ignore_{ai_id}", "false")
            state.set_config(f"heat_ignore_{ai_id}", "false" if current == "true" else "true")
        return handler

    def open_controller(icon, item):
        import subprocess
        subprocess.Popen(["python3", "-m", "controller.app"])

    menu = pystray.Menu(
        pystray.MenuItem("Heat Mode", pystray.Menu(
            pystray.MenuItem("Universal", set_universal,
                           checked=lambda item: get_heat_mode(item) == "universal"),
            pystray.MenuItem("Per-CLI", set_per_cli,
                           checked=lambda item: get_heat_mode(item) == "per-cli"),
        )),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Claude Code", toggle_ignore("claude"),
                        checked=lambda item: state.get_config("heat_ignore_claude", "false") != "true"),
        pystray.MenuItem("Gemini CLI", toggle_ignore("gemini"),
                        checked=lambda item: state.get_config("heat_ignore_gemini", "false") != "true"),
        pystray.MenuItem("Codex", toggle_ignore("codex"),
                        checked=lambda item: state.get_config("heat_ignore_codex", "false") != "true"),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Controller", open_controller),
        pystray.MenuItem("Quit", lambda icon, item: icon.stop()),
    )

    icon = pystray.Icon("ember-memory", image, "Ember Memory", menu)
    icon.run()
```

- [ ] **Step 2: Add tray launch entry point**

```python
# ember_memory/__main__.py or controller/__main__.py
if __name__ == "__main__":
    from controller.tray import create_tray
    create_tray()
```

- [ ] **Step 3: Test manually — run tray, verify menu items toggle state**
- [ ] **Step 4: Commit**

---

### Task 9: Setup Wizard Update

**Files:**
- Update: `scripts/setup.py` or integrate into controller/app.py

- [ ] **Step 1: Update wizard flow for v2**

New flow:
1. Detect installed CLIs (which claude, which gemini, which codex)
2. Choose embedding provider (Ollama/OpenAI/Google with validation)
3. Choose storage backend (3 tiers: quick start / self-hosted / cloud)
4. Create initial collections (shared:general at minimum)
5. Wire hooks into each detected CLI
6. Test retrieval with sample query
7. Offer to start system tray

- [ ] **Step 2: Test the full setup flow manually**
- [ ] **Step 3: Commit**

---

### Task 10: README Rewrite

**Files:**
- Rewrite: `README.md`

- [ ] **Step 1: Write the new README**

Structure:
1. One-liner: "Persistent memory for AI coding CLIs — with game-AI intelligence."
2. What It Does (5 bullets — multi-CLI, multi-backend, auto-retrieval, Engine scoring, desktop controller)
3. Architecture diagram (ASCII: CLI hooks -> shared engine -> backends)
4. Comparison table (vs claude-mem, Basic Memory, native memory)
5. Quick Start (4 steps: clone, install, wizard, done)
6. Supported CLIs (Claude Code, Gemini CLI, Codex with setup details)
7. Supported Backends (8 backends with pip extras)
8. Embedding Providers (3 providers with trade-offs)
9. The Ember Engine (3-sentence explainer + heat/decay/connections overview)
10. Configuration (env vars table)
11. Desktop Controller + System Tray
12. MCP Tools table
13. Links to KFS, CinderACE, CinderVOX
14. License (MIT)

- [ ] **Step 2: Update PRIVACY.md for multi-provider reality**

Ollama = zero network. OpenAI/Google = API calls for embedding text. Storage always local.

- [ ] **Step 3: Commit**

---

### Task 11: Version Bump + Final Polish

**Files:**
- Update: `.claude-plugin/plugin.json` version to 2.0.0
- Update: `ember_memory/__init__.py` version
- Clean up: remove deprecated v1 modules if safe

- [ ] **Step 1: Bump version to 2.0.0 everywhere**
- [ ] **Step 2: Run full test suite across ALL plans**

```bash
cd ~/ember-memory && python -m pytest tests/ -v
```

- [ ] **Step 3: Manual smoke test**

Full flow: install fresh, run wizard, store a memory, retrieve it, check engine state, verify tray works.

- [ ] **Step 4: Commit and tag**

```bash
git tag v2.0.0
```

- [ ] **Step 5: Push to GitHub**

---

## Plan 4 Complete — v2.0 Shipped

After Plan 4:
- All three CLI integrations wired (Claude Code, Gemini CLI, Codex)
- Desktop controller with engine dashboard
- System tray with heat mode controls
- README rewritten for multi-CLI launch
- PRIVACY.md updated
- v2.0.0 tagged and pushed

**Launch sequence:**
1. Push to GitHub
2. Post to r/ClaudeAI (primary)
3. Post to r/LocalLLaMA (local-first angle)
4. X post (secondary)
5. Submit to Anthropic plugin marketplace (update from v1)
