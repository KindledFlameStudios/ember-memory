#!/usr/bin/env python3
"""
Ember Memory — Settings & Management App
=========================================
Native desktop app for configuring and managing Ember Memory.
Uses pywebview for a native window with modern HTML/CSS frontend.

Run: python setup_wizard.py
"""

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
# On Linux with conda, the system WebKit2 typelib may not be on GI's search path.
# Add the standard system typelib directory so pywebview can find GTK + WebKit2.
if platform.system() == "Linux":
    sys_typelib = "/usr/lib/x86_64-linux-gnu/girepository-1.0"
    if os.path.isdir(sys_typelib):
        os.environ["GI_TYPELIB_PATH"] = sys_typelib + ":" + os.environ.get("GI_TYPELIB_PATH", "")
    # Suppress harmless ATK accessibility bridge warnings
    os.environ["NO_AT_BRIDGE"] = "1"

# Suppress ChromaDB telemetry noise
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

# ── Paths ────────────────────────────────────────────────────────────────────

DEFAULT_DATA_DIR = os.path.expanduser("~/.ember-memory")
CONFIG_HOME = os.path.expanduser("~/.ember-memory")
CONFIG_FILE = os.path.join(CONFIG_HOME, "config.env")
CLAUDE_JSON = os.path.expanduser("~/.claude.json")
CLAUDE_SETTINGS = os.path.expanduser("~/.claude/settings.json")
GEMINI_SETTINGS = os.path.expanduser("~/.gemini/settings.json")
CODEX_CONFIG = os.path.expanduser("~/.codex/config.toml")
CODEX_HOOKS = os.path.expanduser("~/.codex/hooks.json")
EMBER_ROOT = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_AI_IDS = ("claude", "gemini", "codex")


# ── Config I/O ───────────────────────────────────────────────────────────────

def load_config():
    defaults = {
        "backend": "chromadb",
        "data_dir": DEFAULT_DATA_DIR,
        "embedding_provider": "ollama",
        "embedding_model": "bge-m3",
        "ollama_url": "http://localhost:11434/api/embeddings",
        "openai_key": "",
        "google_key": "",
        "default_collection": "general",
        "similarity_threshold": "0.45",
        "max_results": "5",
        "max_preview": "800",
    }
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    key = key.replace("EMBER_", "").lower()
                    if key == "max_hook_results":
                        key = "max_results"
                    elif key == "max_preview_chars":
                        key = "max_preview"
                    defaults[key] = val
    return defaults


def save_config(config):
    """Write config.env to the fixed config home (~/.ember-memory/).

    Config file is always at CONFIG_HOME, separate from the data directory.
    This avoids the chicken-and-egg: config tells us where data lives.
    """
    os.makedirs(CONFIG_HOME, exist_ok=True)
    lines = [
        f"EMBER_BACKEND={config['backend']}",
        f"EMBER_DATA_DIR={config['data_dir']}",
        f"EMBER_EMBEDDING_PROVIDER={config['embedding_provider']}",
        f"EMBER_EMBEDDING_MODEL={config['embedding_model']}",
        f"EMBER_OLLAMA_URL={config['ollama_url']}",
        f"EMBER_OPENAI_API_KEY={config.get('openai_key', '')}",
        f"EMBER_GOOGLE_API_KEY={config.get('google_key', '')}",
        f"EMBER_DEFAULT_COLLECTION={config['default_collection']}",
        f"EMBER_SIMILARITY_THRESHOLD={config['similarity_threshold']}",
        f"EMBER_MAX_HOOK_RESULTS={config['max_results']}",
        f"EMBER_MAX_PREVIEW_CHARS={config['max_preview']}",
    ]
    with open(CONFIG_FILE, 'w') as f:
        f.write("\n".join(lines) + "\n")


def _codex_server_command():
    """Return a stdio MCP launch command that works from a source checkout."""
    bootstrap = (
        "import sys; "
        f"sys.path.insert(0, {EMBER_ROOT!r}); "
        "from ember_memory.server import mcp; "
        "mcp.run(transport='stdio')"
    )
    return sys.executable, ["-c", bootstrap]


def _toml_quote(value):
    return json.dumps(str(value))


def _toml_array(values):
    return "[" + ", ".join(_toml_quote(v) for v in values) + "]"


def _upsert_toml_table(text, table_name, body_lines):
    """Replace or append a TOML table while preserving unrelated content."""
    lines = text.splitlines()
    header_re = re.compile(r"^\[([^\]]+)\]\s*$")
    headers = []
    for idx, line in enumerate(lines):
        match = header_re.match(line.strip())
        if match:
            headers.append((match.group(1), idx))

    replacement = [f"[{table_name}]", *body_lines]

    for pos, (name, start_idx) in enumerate(headers):
        if name != table_name:
            continue
        end_idx = headers[pos + 1][1] if pos + 1 < len(headers) else len(lines)
        new_lines = lines[:start_idx] + replacement + lines[end_idx:]
        return "\n".join(new_lines).rstrip() + "\n"

    if lines and lines[-1] != "":
        lines.append("")
    lines.extend(replacement)
    return "\n".join(lines).rstrip() + "\n"


def _upsert_toml_key(text, table_name, key, value_literal):
    """Set one key inside a TOML table while preserving other table entries."""
    lines = text.splitlines()
    header_re = re.compile(r"^\[([^\]]+)\]\s*$")
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")
    headers = []
    for idx, line in enumerate(lines):
        match = header_re.match(line.strip())
        if match:
            headers.append((match.group(1), idx))

    for pos, (name, start_idx) in enumerate(headers):
        if name != table_name:
            continue
        end_idx = headers[pos + 1][1] if pos + 1 < len(headers) else len(lines)
        body = lines[start_idx + 1:end_idx]
        replaced = False
        new_body = []
        for line in body:
            if key_re.match(line):
                new_body.append(f"{key} = {value_literal}")
                replaced = True
            else:
                new_body.append(line)
        if not replaced:
            new_body.append(f"{key} = {value_literal}")
        new_lines = lines[:start_idx + 1] + new_body + lines[end_idx:]
        return "\n".join(new_lines).rstrip() + "\n"

    if lines and lines[-1] != "":
        lines.append("")
    lines.extend([f"[{table_name}]", f"{key} = {value_literal}"])
    return "\n".join(lines).rstrip() + "\n"


def _load_toml(path):
    if not os.path.exists(path):
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _codex_mcp_configured():
    config_data = _load_toml(CODEX_CONFIG)
    return "ember-memory" in config_data.get("mcp_servers", {})


def _codex_hooks_feature_enabled():
    config_data = _load_toml(CODEX_CONFIG)
    return bool(config_data.get("features", {}).get("codex_hooks"))


def _codex_hook_script_path():
    return os.path.join(EMBER_ROOT, "integrations", "codex", "hook.py")


def _codex_hook_configured():
    if not os.path.exists(CODEX_HOOKS):
        return False
    try:
        with open(CODEX_HOOKS, "r") as f:
            data = json.load(f)
    except Exception:
        return False

    for entry in data.get("hooks", {}).get("UserPromptSubmit", []):
        if not isinstance(entry, dict):
            continue
        for hook in entry.get("hooks", []):
            if not isinstance(hook, dict):
                continue
            command = hook.get("command", "")
            if "ember" in command.lower() or _codex_hook_script_path() in command:
                return True
    return False


def _write_codex_hooks():
    os.makedirs(os.path.dirname(CODEX_HOOKS), exist_ok=True)
    hook_cmd = f"{sys.executable} {_codex_hook_script_path()}"
    hooks = {
        "hooks": {
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_cmd,
                            "timeout": 10,
                            "statusMessage": "Retrieving Ember Memory context",
                        }
                    ]
                }
            ]
        }
    }
    with open(CODEX_HOOKS, "w") as f:
        json.dump(hooks, f, indent=2)


def _write_codex_config(data_dir):
    os.makedirs(os.path.dirname(CODEX_CONFIG), exist_ok=True)
    command, args = _codex_server_command()

    if os.path.exists(CODEX_CONFIG):
        with open(CODEX_CONFIG, "r") as f:
            config_text = f.read()
    else:
        config_text = ""

    config_text = _upsert_toml_table(
        config_text,
        "mcp_servers.ember-memory",
        [
            f"command = {_toml_quote(command)}",
            f"args = {_toml_array(args)}",
            "startup_timeout_sec = 15",
            "tool_timeout_sec = 30",
        ],
    )
    config_text = _upsert_toml_table(
        config_text,
        "mcp_servers.ember-memory.env",
        [
            'EMBER_AI_ID = "codex"',
            f"EMBER_DATA_DIR = {_toml_quote(data_dir)}",
        ],
    )
    config_text = _upsert_toml_key(config_text, "features", "codex_hooks", "true")

    with open(CODEX_CONFIG, "w") as f:
        f.write(config_text)


def normalize_dashboard_ai_id(ai_id):
    raw = str(ai_id or "").strip().lower()
    if not raw or raw == "all":
        return None
    return raw


def _get_cli_from_session(session_scope):
    """Map a session ID back to its parent CLI for dashboard aggregation.
    cc-12345 -> claude, gemini-98765 -> gemini, codex-555 -> codex"""
    s = str(session_scope)
    if s.startswith("cc-") or s.startswith("claude"):
        return "claude"
    if s.startswith("gemini"):
        return "gemini"
    if s.startswith("codex"):
        return "codex"
    # Backward compatibility: older Codex hook installs wrote raw thread IDs
    # (UUID-like strings such as 019d...-....) directly into heat scope.
    if re.match(r"^[0-9a-f]{8}-[0-9a-f-]{27,}$", s):
        return "codex"
    return None


def get_dashboard_heat(state, ai_id=None):
    selected_ai = normalize_dashboard_ai_id(ai_id)

    # Get ALL heat entries from the database (all scopes)
    conn = state._conn
    rows = conn.execute("SELECT ai_id, memory_id, heat FROM heat_map WHERE heat > 0.01").fetchall()

    merged = {}
    for row in rows:
        scope = row["ai_id"] if row["ai_id"] else ""
        mem_id = row["memory_id"]
        heat = float(row["heat"])

        # Map session IDs to parent CLI for dashboard
        parent_cli = _get_cli_from_session(scope) if scope else None

        if selected_ai is not None:
            # Filtered view: only show entries belonging to this CLI
            if parent_cli == selected_ai or scope == selected_ai:
                merged[mem_id] = merged.get(mem_id, 0.0) + heat
        else:
            # "All" view: aggregate everything
            merged[mem_id] = merged.get(mem_id, 0.0) + heat

    return merged


def get_dashboard_connections(state, ai_id=None, min_strength=0.0):
    """Return dashboard connection rows, optionally scoped by CLI or session."""
    conn = state._conn
    rows = conn.execute(
        "SELECT id_a, id_b, strength FROM connections WHERE strength > ? ORDER BY strength DESC",
        (float(min_strength),),
    ).fetchall()

    selected_ai = normalize_dashboard_ai_id(ai_id)
    if selected_ai is None:
        return rows

    visible_ids = set(get_dashboard_heat(state, ai_id=selected_ai).keys())
    if not visible_ids:
        return []

    return [row for row in rows if row["id_a"] in visible_ids and row["id_b"] in visible_ids]


def get_last_retrieval_path(data_dir, ai_id=None):
    selected_ai = normalize_dashboard_ai_id(ai_id)
    if selected_ai is None:
        return os.path.join(data_dir, "last_retrieval.json")
    safe_ai = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in selected_ai)
    return os.path.join(data_dir, f"last_retrieval_{safe_ai}.json")


def read_json_file(path):
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def get_engine_db_path():
    cfg = load_config()
    return os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")


def get_engine_state(create=True):
    from ember_memory.core.engine.state import EngineState

    db_path = get_engine_db_path()
    if create:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return EngineState(db_path=db_path)


def resolve_memory_id(state, memory_id):
    """Resolve a memory ID or unique prefix to the stored full ID."""
    raw_id = str(memory_id or "").strip()
    if not raw_id:
        return raw_id

    row = state._conn.execute(
        "SELECT memory_id FROM memory_meta WHERE memory_id = ?",
        (raw_id,),
    ).fetchone()
    if row:
        return row["memory_id"]

    rows = state._conn.execute(
        "SELECT memory_id FROM memory_meta WHERE memory_id LIKE ? ORDER BY memory_id LIMIT 2",
        (raw_id + "%",),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]["memory_id"]

    return raw_id


# ── API Backend (exposed to JS via pywebview) ────────────────────────────────

class EmberAPI:
    """Python backend exposed to the webview frontend via window.pywebview.api"""

    def get_config(self):
        return load_config()

    def save_settings(self, incoming):
        try:
            # Merge incoming partial config with current config
            # so missing fields don't cause KeyErrors
            config = load_config()

            # Map UI field names to config keys (handle mismatches)
            field_map = {
                "openai_api_key": "openai_key",
                "google_api_key": "google_key",
                "max_preview_chars": "max_preview",
            }
            for ui_key, config_key in field_map.items():
                if ui_key in incoming:
                    incoming[config_key] = incoming.pop(ui_key)

            config.update(incoming)
            save_config(config)
            return {"ok": True, "msg": "Settings saved. Restart your CLIs to apply."}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def check_prerequisites(self):
        results = {}

        # Ollama
        if shutil.which("ollama"):
            try:
                r = subprocess.run(["ollama", "list"], capture_output=True,
                                   text=True, timeout=5)
                if r.returncode == 0:
                    results["ollama"] = {"ok": True, "msg": "Running"}
                    cfg = load_config()
                    model = cfg.get("embedding_model", "bge-m3")
                    if model in r.stdout:
                        results["model"] = {"ok": True, "msg": f"{model} available"}
                    else:
                        results["model"] = {"ok": False,
                                            "msg": f"Not found. Run: ollama pull {model}"}
                else:
                    results["ollama"] = {"ok": False, "msg": "Not running. Start: ollama serve"}
                    results["model"] = {"ok": False, "msg": "Needs Ollama"}
            except Exception:
                results["ollama"] = {"ok": False, "msg": "Not responding"}
                results["model"] = {"ok": False, "msg": "Needs Ollama"}
        else:
            results["ollama"] = {"ok": False, "msg": "Not installed — ollama.com"}
            results["model"] = {"ok": False, "msg": "Needs Ollama"}

        # ChromaDB
        try:
            import chromadb  # noqa: F401
            results["chromadb"] = {"ok": True, "msg": "Installed"}
        except ImportError:
            results["chromadb"] = {"ok": False, "msg": "pip install chromadb"}

        # MCP
        try:
            import mcp  # noqa: F401
            results["mcp"] = {"ok": True, "msg": "Installed"}
        except ImportError:
            results["mcp"] = {"ok": False, "msg": "pip install 'mcp[cli]'"}

        return results

    def check_integration(self):
        result = {
            "mcp": False,
            "hook": False,
            "data_dir": False,
            "config": False,
            "claude_mcp": False,
            "claude_hook": False,
            "gemini_mcp": False,
            "gemini_hook": False,
            "codex_mcp": False,
            "codex_hook": False,
        }

        cfg = load_config()
        data_dir = cfg.get("data_dir", DEFAULT_DATA_DIR)
        if os.path.isdir(data_dir):
            result["data_dir"] = True
        if os.path.exists(CONFIG_FILE):
            result["config"] = True

        if os.path.exists(CLAUDE_JSON):
            try:
                with open(CLAUDE_JSON, 'r') as f:
                    data = json.load(f)
                if "ember-memory" in data.get("mcpServers", {}):
                    result["claude_mcp"] = True
            except Exception:
                pass

        if os.path.exists(CLAUDE_SETTINGS):
            try:
                with open(CLAUDE_SETTINGS, 'r') as f:
                    data = json.load(f)
                for entry in data.get("hooks", {}).get("UserPromptSubmit", []):
                    if isinstance(entry, dict):
                        for h in entry.get("hooks", []):
                            if "ember" in h.get("command", "").lower():
                                result["claude_hook"] = True
            except Exception:
                pass

        if os.path.exists(GEMINI_SETTINGS):
            try:
                with open(GEMINI_SETTINGS, 'r') as f:
                    data = json.load(f)
                if "ember-memory" in data.get("mcpServers", {}):
                    result["gemini_mcp"] = True
                for entry in data.get("hooks", {}).get("BeforeAgent", []):
                    if isinstance(entry, dict):
                        for h in entry.get("hooks", []):
                            if "ember" in h.get("name", "").lower() or "ember" in h.get("command", "").lower():
                                result["gemini_hook"] = True
            except Exception:
                pass

        try:
            result["codex_mcp"] = _codex_mcp_configured()
        except Exception:
            pass
        try:
            result["codex_hook"] = _codex_hooks_feature_enabled() and _codex_hook_configured()
        except Exception:
            pass

        result["mcp"] = bool(result["claude_mcp"] or result["gemini_mcp"] or result["codex_mcp"])
        result["hook"] = bool(result["claude_hook"] or result["gemini_hook"] or result["codex_hook"])

        return result

    def run_install(self):
        """Idempotent install: register Ember Memory with supported local CLIs.

        All real settings live in config.env inside the data directory. CLI
        config files only get the launch pointers and hook wiring they need.
        """
        errors = []
        cfg = load_config()
        data_dir = cfg.get("data_dir", DEFAULT_DATA_DIR)

        # 1. Create data directory + save config.env
        try:
            os.makedirs(data_dir, exist_ok=True)
            save_config(cfg)
        except Exception as e:
            errors.append(f"Data dir: {e}")

        # 2. MCP server — register in .claude.json (idempotent)
        try:
            server_path = os.path.join(EMBER_ROOT, "ember_memory", "server.py")
            python_path = sys.executable

            config_data = {}
            if os.path.exists(CLAUDE_JSON):
                with open(CLAUDE_JSON, 'r') as f:
                    config_data = json.load(f)

            if "mcpServers" not in config_data:
                config_data["mcpServers"] = {}

            existing = config_data["mcpServers"].get("ember-memory")
            desired = {
                "command": python_path,
                "args": [server_path],
            }

            # Only write if missing or changed
            if existing != desired:
                config_data["mcpServers"]["ember-memory"] = desired
                with open(CLAUDE_JSON, 'w') as f:
                    json.dump(config_data, f, indent=2)
        except Exception as e:
            errors.append(f"MCP: {e}")

        # 3. Hook — register in settings.json (idempotent)
        try:
            hook_path = os.path.join(EMBER_ROOT, "ember_memory", "hook.py")
            python_path = sys.executable
            hook_cmd = f"{python_path} {hook_path}"

            settings = {}
            os.makedirs(os.path.dirname(CLAUDE_SETTINGS), exist_ok=True)
            if os.path.exists(CLAUDE_SETTINGS):
                with open(CLAUDE_SETTINGS, 'r') as f:
                    settings = json.load(f)

            if "hooks" not in settings:
                settings["hooks"] = {}
            if "UserPromptSubmit" not in settings["hooks"]:
                settings["hooks"]["UserPromptSubmit"] = []

            # Check if an ember hook already exists — update in-place
            found = False
            for entry in settings["hooks"]["UserPromptSubmit"]:
                if isinstance(entry, dict) and "hooks" in entry:
                    for h in entry["hooks"]:
                        if "ember" in h.get("command", "").lower():
                            h["command"] = hook_cmd
                            found = True

            if not found:
                settings["hooks"]["UserPromptSubmit"].append({
                    "matcher": "*",
                    "hooks": [{"type": "command", "command": hook_cmd, "timeout": 10}],
                })

            with open(CLAUDE_SETTINGS, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            errors.append(f"Hook: {e}")

        # 4. Gemini CLI — register hook + MCP if installed
        if shutil.which("gemini"):
            try:
                gemini_hook_path = os.path.join(EMBER_ROOT, "integrations", "gemini_cli", "hook.py")
                gs = {}
                if os.path.exists(GEMINI_SETTINGS):
                    with open(GEMINI_SETTINGS, 'r') as f:
                        gs = json.load(f)

                # MCP server
                if "mcpServers" not in gs:
                    gs["mcpServers"] = {}
                gs["mcpServers"]["ember-memory"] = {
                    "command": sys.executable,
                    "args": ["-m", "ember_memory.server"],
                    "timeout": 30000
                }

                # BeforeAgent hook
                if "hooks" not in gs:
                    gs["hooks"] = {}
                if "BeforeAgent" not in gs["hooks"]:
                    gs["hooks"]["BeforeAgent"] = []

                # Check if ember hook already exists
                ember_exists = False
                for entry in gs["hooks"]["BeforeAgent"]:
                    if isinstance(entry, dict):
                        for h in entry.get("hooks", []):
                            if "ember" in h.get("name", "").lower() or "ember" in h.get("command", "").lower():
                                h["command"] = f"{sys.executable} {gemini_hook_path}"
                                ember_exists = True

                if not ember_exists:
                    gs["hooks"]["BeforeAgent"].append({
                        "matcher": "*",
                        "hooks": [{
                            "name": "ember-memory",
                            "type": "command",
                            "command": f"{sys.executable} {gemini_hook_path}",
                            "timeout": 10000
                        }]
                    })

                os.makedirs(os.path.dirname(GEMINI_SETTINGS), exist_ok=True)
                with open(GEMINI_SETTINGS, 'w') as f:
                    json.dump(gs, f, indent=2)
            except Exception as e:
                errors.append(f"Gemini CLI: {e}")

        # 5. Codex — register MCP server if installed
        if shutil.which("codex"):
            try:
                _write_codex_config(data_dir)
                _write_codex_hooks()
            except Exception as e:
                errors.append(f"Codex: {e}")

        if errors:
            return {"ok": False, "msg": "; ".join(errors)}
        return {"ok": True, "msg": "Installed! Restart your CLIs to activate."}

    def get_collections(self):
        """List all collections with counts — uses v2 backend."""
        try:
            from ember_memory.core.backends.loader import get_backend_v2
            backend = get_backend_v2()
            collections = backend.list_collections()
            return {"ok": True, "collections": sorted(collections, key=lambda c: c["name"])}
        except Exception as e:
            return {"ok": False, "collections": [], "msg": str(e)}

    def get_workspaces(self):
        """Get all workspace configurations."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            state = EngineState(db_path=db_path)
            return {"ok": True, "workspaces": state.get_workspace_config()}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def save_workspace(self, name, label, collections, cwd=""):
        """Create or update a workspace. collections is a dict of {col_name: bool}.
        cwd is optional — when set, the workspace auto-activates for sessions in that directory."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            state = EngineState(db_path=db_path)
            ws_config = state.get_workspace_config()
            ws_entry = {"label": label, "collections": collections}
            if cwd:
                ws_entry["cwd"] = cwd
            elif name in ws_config and "cwd" in ws_config[name]:
                ws_entry["cwd"] = ws_config[name]["cwd"]
            ws_config[name] = ws_entry
            state.save_workspace_config(ws_config)
            return {"ok": True, "msg": f"Workspace '{label}' saved"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def delete_workspace(self, name):
        """Delete a workspace."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            state = EngineState(db_path=db_path)
            ws_config = state.get_workspace_config()
            ws_config.pop(name, None)
            state.save_workspace_config(ws_config)
            return {"ok": True, "msg": f"Workspace '{name}' deleted"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def get_launch_dirs(self):
        """Get configured launch directories for each CLI."""
        from ember_memory.core.engine.state import EngineState
        cfg = load_config()
        db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        state = EngineState(db_path=db_path)
        home = os.path.expanduser("~")
        return {
            "ok": True,
            "dirs": {
                "claude": state.get_config("launch_dir_claude", home),
                "gemini": state.get_config("launch_dir_gemini", home),
                "codex": state.get_config("launch_dir_codex", home),
            }
        }

    def set_launch_dir(self, cli, path):
        """Set the launch directory for a CLI."""
        from ember_memory.core.engine.state import EngineState
        cfg = load_config()
        db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        state = EngineState(db_path=db_path)
        state.set_config(f"launch_dir_{cli}", path)
        return {"ok": True, "msg": f"{cli} launch dir set to {path}"}

    def launch_cli(self, cli, workspace=""):
        """Launch a CLI terminal with a specific workspace active."""
        import shlex
        import subprocess

        # Get configured launch directory
        from ember_memory.core.engine.state import EngineState
        cfg = load_config()
        db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        state = EngineState(db_path=db_path)
        home_dir = state.get_config(f"launch_dir_{cli}", os.path.expanduser("~"))

        commands = {
            "claude": "claude",
            "gemini": "gemini",
            "codex": "codex",
        }
        cmd = commands.get(cli)
        if not cmd:
            return {"ok": False, "msg": f"Unknown CLI: {cli}"}
        if not shutil.which(cmd):
            return {"ok": False, "msg": f"{cli} is not installed"}

        env = dict(os.environ)
        if workspace:
            env["EMBER_WORKSPACE"] = workspace
        env["EMBER_AI_ID"] = cli if cli != "claude" else "claude"
        safe_ws = shlex.quote(workspace)
        safe_dir = shlex.quote(home_dir)

        try:
            if platform.system() == "Linux":
                # Try gnome-terminal, then xterm, then just subprocess
                if shutil.which("gnome-terminal"):
                    ws_export = f"export EMBER_WORKSPACE={safe_ws} EMBER_AI_ID='{cli}'; " if workspace else ""
                    subprocess.Popen([
                        "gnome-terminal", "--", "bash", "-c",
                        f"cd {safe_dir} && {ws_export}{cmd}; exec bash"
                    ])
                elif shutil.which("xterm"):
                    subprocess.Popen(["xterm", "-e", cmd], env=env, cwd=home_dir)
                else:
                    subprocess.Popen([cmd], env=env, cwd=home_dir)
            elif platform.system() == "Darwin":
                ws_export = f"export EMBER_WORKSPACE={safe_ws} EMBER_AI_ID='{cli}' && " if workspace else ""
                subprocess.Popen([
                    "osascript", "-e",
                    f'tell app "Terminal" to do script "cd {safe_dir} && {ws_export}{cmd}"'
                ])
            else:
                subprocess.Popen([cmd], env=env, cwd=home_dir)

            label = workspace or "default"
            return {"ok": True, "msg": f"Launched {cli} with workspace '{label}'"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def create_collection(self, name, scope="shared"):
        """Create a collection with optional AI namespace."""
        try:
            from ember_memory.core.backends.loader import get_backend_v2
            from ember_memory.core.embeddings.loader import get_embedding_provider
            from ember_memory.core.namespaces import resolve_collection_name
            backend = get_backend_v2()
            embedder = get_embedding_provider()
            full_name = resolve_collection_name(name, scope)
            backend.create_collection(full_name, dimension=embedder.dimension())
            return {"ok": True, "msg": f"Collection '{full_name}' created"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def import_files(self, paths, collection_name, scope="shared"):
        """Import one or more files or directories into a collection."""
        try:
            import hashlib
            import re as _re
            from ember_memory.core.namespaces import parse_collection_name, resolve_collection_name
            from ember_memory.core.embeddings.loader import get_embedding_provider
            from ember_memory.core.backends.loader import get_backend_v2

            raw_collection_name = str(collection_name or "").strip()
            if not raw_collection_name:
                return {"ok": False, "msg": "Collection name is required"}

            parsed_scope, parsed_topic = parse_collection_name(raw_collection_name)
            if parsed_topic != raw_collection_name and scope == "shared":
                collection_name = parsed_topic
                scope = parsed_scope
            else:
                collection_name = raw_collection_name

            full_name = resolve_collection_name(collection_name, scope)
            embedder = get_embedding_provider()
            backend = get_backend_v2()
            dim = embedder.dimension()

            try:
                backend.create_collection(full_name, dimension=dim)
            except Exception:
                pass

            all_files = []
            if isinstance(paths, str):
                paths = [paths]

            supported_exts = ('.md', '.txt', '.json', '.jsonl')
            for path in paths or []:
                if not path:
                    continue
                if os.path.isdir(path):
                    for fname in os.listdir(path):
                        fpath = os.path.join(path, fname)
                        if os.path.isfile(fpath) and fname.lower().endswith(supported_exts):
                            all_files.append(fpath)
                elif os.path.isfile(path) and path.lower().endswith(supported_exts):
                    all_files.append(path)

            if not all_files:
                return {"ok": False, "msg": "No supported files found (.md, .txt, .json, .jsonl)"}

            chunks_added = 0
            for fpath in all_files:
                with open(fpath, 'r', errors='replace') as f:
                    content = f.read().strip()

                if not content or len(content) < 20:
                    continue

                fname = os.path.basename(fpath)

                chunks = []
                if '## ' in content or '# ' in content:
                    sections = _re.split(r'(?=^#{1,3} )', content, flags=_re.MULTILINE)
                    for section in sections:
                        section = section.strip()
                        if len(section) > 50:
                            chunks.append(section)

                if not chunks:
                    max_chunk = 1500
                    for i in range(0, len(content), max_chunk):
                        chunk = content[i:i + max_chunk].strip()
                        if len(chunk) > 50:
                            chunks.append(chunk)

                for i, chunk in enumerate(chunks):
                    doc_id = hashlib.md5(f'{fname}:{i}:{chunk[:100]}'.encode()).hexdigest()
                    try:
                        embedding = embedder.embed(chunk)
                        backend.insert(
                            collection=full_name,
                            doc_id=doc_id,
                            content=chunk,
                            embedding=embedding,
                            metadata={
                                'source': fname,
                                'chunk': i,
                                'scope': scope,
                                'topic': collection_name,
                            },
                        )
                        chunks_added += 1
                    except Exception:
                        pass

            return {
                "ok": True,
                "msg": f"Imported {len(all_files)} files into '{full_name}' ({chunks_added} chunks)",
                "files": len(all_files),
                "collection": full_name,
                "chunks": chunks_added,
            }
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def get_suggested_queries(self, collection_name):
        """Get suggested first queries for a collection after import."""
        return {
            "ok": True,
            "queries": [
                f"What do we know about {collection_name}?",
                f"What decisions were made regarding {collection_name}?",
                f"What are the key themes in {collection_name}?",
                f"What changed over time in {collection_name}?",
            ]
        }

    def generate_handoff(self, topic="", ai_id="claude"):
        """Generate a hand-off packet from the controller."""
        try:
            from ember_memory.core.search import retrieve
            from ember_memory.core.embeddings.loader import get_embedding_provider
            from ember_memory.core.backends.loader import get_backend_v2

            embedder = get_embedding_provider()
            backend = get_backend_v2()
            engine_db_path = os.path.join(
                load_config().get("data_dir", DEFAULT_DATA_DIR),
                "engine",
                "engine.db",
            )

            if topic:
                results = retrieve(
                    prompt=topic,
                    ai_id=ai_id,
                    backend=backend,
                    embedder=embedder,
                    limit=5,
                    similarity_threshold=0.3,
                    engine_db_path=engine_db_path,
                )
                lines = [
                    "=== Hand-off Packet ===",
                    f"Topic: {topic}",
                    f"Generated: {datetime.now().isoformat()}",
                    "",
                    "## Key Context",
                ]
                for i, result in enumerate(results, 1):
                    preview = result.content[:200].replace("\n", " ")
                    lines.append(f"{i}. [{result.collection}] {preview}")
                lines.append("")
                lines.append("## Suggested Next Steps")
                lines.append(f'- "What progress have we made on {topic}?"')
                lines.append(f'- "What decisions were made about {topic}?"')
                return {"ok": True, "packet": "\n".join(lines)}

            return {"ok": True, "packet": "Provide a topic to generate a hand-off packet."}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def delete_collection(self, name):
        cfg = load_config()
        try:
            from ember_memory.core.backends.loader import get_backend_v2
            backend = get_backend_v2()
            backend.delete_collection(name)
            return {"ok": True, "msg": f"Collection '{name}' deleted"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def run_ingest(self, directory, collection=None, sync=False):
        try:
            cmd = [sys.executable, "-m", "ember_memory.ingest", directory]
            if collection:
                cmd += ["--collection", collection]
            if sync:
                cmd += ["--sync"]
            result = subprocess.run(cmd, capture_output=True, text=True,
                                     timeout=300, cwd=EMBER_ROOT)
            output = result.stdout.strip() or result.stderr.strip() or "Done"
            last_line = output.split("\n")[-1]
            return {"ok": result.returncode == 0, "msg": last_line}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def test_ollama(self):
        cfg = load_config()
        try:
            import urllib.request
            url = cfg.get("ollama_url", "").replace("/api/embeddings", "/api/tags")
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                models = [m.get("name", "") for m in data.get("models", [])]
                wanted = cfg.get("embedding_model", "bge-m3")
                if any(wanted in m for m in models):
                    return {"ok": True, "msg": f"Connected — {wanted} available"}
                else:
                    return {"ok": False,
                            "msg": f"Connected but {wanted} not found. Run: ollama pull {wanted}"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def get_ollama_models(self):
        """Discover available Ollama embedding models."""
        cfg = load_config()
        try:
            import urllib.request
            url = cfg.get("ollama_url", "").replace("/api/embeddings", "/api/tags")
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                models = []
                for m in data.get("models", []):
                    name = m.get("name", "")
                    size = m.get("size", 0)
                    # Filter for embedding models by common naming patterns
                    is_embed = any(kw in name.lower() for kw in
                                   ["embed", "bge", "e5", "gte", "nomic", "mxbai"])
                    models.append({
                        "name": name,
                        "size_gb": round(size / (1024**3), 1) if size else 0,
                        "is_embedding": is_embed,
                    })
                current = cfg.get("embedding_model", "bge-m3")
                return {"ok": True, "models": models, "current": current}
        except Exception as e:
            return {"ok": False, "models": [], "msg": str(e)}

    def set_embedding_model(self, model_name):
        """Switch the active Ollama embedding model."""
        try:
            config = load_config()
            config["embedding_model"] = model_name
            save_config(config)
            return {"ok": True, "msg": f"Embedding model set to {model_name}. Restart CLIs to apply."}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def browse_files(self):
        """Open native file picker for individual files."""
        import webview
        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=(
                'Markdown files (*.md;*.txt)',
                'JSON files (*.json;*.jsonl)',
                'All files (*.*)',
            ),
        )
        if result and len(result) > 0:
            return {"ok": True, "paths": list(result)}
        return {"ok": False, "paths": []}

    def browse_directory(self):
        """Open native directory picker."""
        import webview
        result = webview.windows[0].create_file_dialog(
            webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            return {"ok": True, "path": result[0]}
        return {"ok": False, "path": ""}

    def get_engine_stats(self, ai_id=None):
        """Get Ember Engine dashboard data."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            data_dir = cfg.get("data_dir", DEFAULT_DATA_DIR)
            db_path = os.path.join(data_dir, "engine", "engine.db")
            if not os.path.exists(db_path):
                return {"ok": True, "stats": {
                    "tick_count": 0, "total_memories_tracked": 0,
                    "hot_memories": 0, "total_connections": 0,
                    "established_connections": 0, "heat_mode": "universal",
                    "ignored_clis": {"claude": False, "gemini": False, "codex": False}
                }}
            state = EngineState(db_path=db_path)
            all_heat = get_dashboard_heat(state, ai_id=ai_id)
            hot_count = sum(1 for heat in all_heat.values() if heat >= 0.5)
            connection_rows = get_dashboard_connections(state, ai_id=ai_id, min_strength=0.0)
            total_connections = len(connection_rows)
            established = sum(1 for row in connection_rows if float(row["strength"]) >= 3.0)
            return {"ok": True, "stats": {
                "tick_count": state.get_tick(),
                "total_memories_tracked": len(all_heat),
                "hot_memories": hot_count,
                "total_connections": total_connections,
                "established_connections": established,
                "heat_mode": state.get_config("heat_mode", "universal"),
                "ignored_clis": {
                    cli_ai: state.get_config(f"heat_ignore_{cli_ai}", "false") == "true"
                    for cli_ai in DASHBOARD_AI_IDS
                },
            }}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def get_last_retrieval(self, ai_id=None):
        """Get the most recent retrieval snapshot for the dashboard."""
        try:
            cfg = load_config()
            data_dir = cfg.get("data_dir", DEFAULT_DATA_DIR)
            retrieval = read_json_file(get_last_retrieval_path(data_dir, ai_id=ai_id))
            if retrieval is None:
                return {"ok": True, "retrieval": None}
            return {"ok": True, "retrieval": retrieval}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def get_all_last_retrievals(self):
        """Get the global and per-AI retrieval snapshots for the dashboard."""
        try:
            cfg = load_config()
            data_dir = cfg.get("data_dir", DEFAULT_DATA_DIR)
            retrievals = {
                "all": read_json_file(get_last_retrieval_path(data_dir)),
            }
            for ai_id in DASHBOARD_AI_IDS:
                retrievals[ai_id] = read_json_file(get_last_retrieval_path(data_dir, ai_id=ai_id))
            return {"ok": True, "retrievals": retrievals}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def rate_memory(self, memory_id, rating):
        """Rate a retrieved memory as helpful (1) or unhelpful (-1)."""
        try:
            state = get_engine_state(create=True)
            resolved_id = resolve_memory_id(state, memory_id)
            key = f"feedback_{resolved_id}"
            current = float(state.get_config(key, "0"))
            new_val = current + float(rating)
            state.set_config(key, str(new_val))
            return {"ok": True, "feedback": new_val, "memory_id": resolved_id}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def pin_memory(self, memory_id, trigger_topic, collection=""):
        """Pin a memory to always surface for a trigger topic."""
        try:
            state = get_engine_state(create=True)
            resolved_id = resolve_memory_id(state, memory_id)
            pins_raw = state.get_config("pinned_memories", "[]")
            pins = json.loads(pins_raw)
            entry = {
                "memory_id": resolved_id,
                "trigger": str(trigger_topic or "").strip().lower(),
                "collection": str(collection or "").strip(),
            }
            if not entry["trigger"]:
                return {"ok": False, "msg": "Pin topic is required"}
            if entry not in pins:
                pins.append(entry)
            state.set_config("pinned_memories", json.dumps(pins))
            return {"ok": True, "msg": f"Pinned for topic: {trigger_topic}", "memory_id": resolved_id}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def unpin_memory(self, memory_id):
        """Remove a pin from a memory."""
        try:
            state = get_engine_state(create=True)
            resolved_id = resolve_memory_id(state, memory_id)
            pins_raw = state.get_config("pinned_memories", "[]")
            pins = json.loads(pins_raw)
            pins = [p for p in pins if p.get("memory_id") != resolved_id]
            state.set_config("pinned_memories", json.dumps(pins))
            return {"ok": True, "msg": "Unpinned", "memory_id": resolved_id}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def get_pins(self):
        """Get all pinned memories."""
        try:
            db_path = get_engine_db_path()
            if not os.path.exists(db_path):
                return {"ok": True, "pins": []}
            state = get_engine_state(create=False)
            pins = json.loads(state.get_config("pinned_memories", "[]"))
            return {"ok": True, "pins": pins}
        except Exception as e:
            return {"ok": False, "pins": [], "msg": str(e)}

    def get_activity_log(self, limit=20, ai_id=None, session_id=None):
        """Get recent activity log entries for the dashboard feed."""
        try:
            cfg = load_config()
            log_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "activity.jsonl")
            if not os.path.exists(log_path):
                return {"ok": True, "entries": []}
            selected_ai = normalize_dashboard_ai_id(ai_id)
            selected_session = str(session_id or "").strip().lower()
            if selected_session == "all":
                selected_session = ""
            try:
                limit = max(1, int(limit))
            except (TypeError, ValueError):
                limit = 20
            entries = []
            with open(log_path, "r") as f:
                lines = f.readlines()
            for line in reversed(lines):
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                    except Exception:
                        pass
                    else:
                        entry_session = str(entry.get("session") or "").strip().lower()
                        if selected_session and entry_session != selected_session:
                            continue
                        if selected_ai is not None:
                            entry_ai = normalize_dashboard_ai_id(entry.get("ai_id"))
                            session_name = entry_session
                            if entry_ai != selected_ai and not (
                                session_name == selected_ai
                                or session_name.startswith(f"{selected_ai}-")
                                or session_name.startswith(f"{selected_ai}_")
                            ):
                                continue
                        entries.append(entry)
                        if len(entries) >= limit:
                            break
            return {"ok": True, "entries": entries}
        except Exception as e:
            return {"ok": False, "entries": [], "msg": str(e)}

    def get_recent_sessions(self, ai_filter=None):
        """Get recent sessions from the activity log, grouped by CLI."""
        try:
            cfg = load_config()
            log_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "activity.jsonl")
            if not os.path.exists(log_path):
                return {"ok": True, "sessions": []}

            selected_filter = normalize_dashboard_ai_id(ai_filter)
            sessions = {}
            with open(log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        sid = str(entry.get("session") or "").strip()
                        ai_id = str(entry.get("ai_id") or "").strip()
                        if not sid:
                            continue

                        if selected_filter is not None:
                            cli = _get_cli_from_session(sid)
                            if cli != selected_filter:
                                continue

                        if sid not in sessions:
                            sessions[sid] = {
                                "id": sid,
                                "ai_id": ai_id,
                                "last_prompt": "",
                                "last_ts": "",
                                "count": 0,
                            }
                        sessions[sid]["last_prompt"] = str(entry.get("prompt") or "")[:80]
                        sessions[sid]["last_ts"] = str(entry.get("ts") or "")
                        sessions[sid]["count"] += 1
                    except Exception:
                        pass

            result = sorted(sessions.values(), key=lambda session: session["last_ts"], reverse=True)
            return {"ok": True, "sessions": result[:20]}
        except Exception as e:
            return {"ok": False, "sessions": [], "msg": str(e)}

    def get_heat_map(self, ai_id=None):
        """Get all heat values for visualization with metadata."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            if not os.path.exists(db_path):
                return {"ok": True, "heat": {}, "meta": {}}
            state = EngineState(db_path=db_path)
            return {
                "ok": True,
                "heat": get_dashboard_heat(state, ai_id=ai_id),
                "meta": state.get_all_memory_meta(),
            }
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def get_connections(self, ai_id=None):
        """Get all connections for graph visualization."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            if not os.path.exists(db_path):
                return {"ok": True, "connections": []}
            state = EngineState(db_path=db_path)
            rows = get_dashboard_connections(state, ai_id=ai_id, min_strength=0.1)[:100]
            connections = [{"source": r[0], "target": r[1], "strength": r[2]} for r in rows]
            meta = state.get_all_memory_meta()
            return {"ok": True, "connections": connections, "meta": meta}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def set_heat_mode(self, mode):
        """Set heat mode: 'universal' or 'per-cli'."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            state = EngineState(db_path=db_path)
            state.set_config("heat_mode", mode)
            return {"ok": True, "msg": f"Heat mode set to {mode}"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def reset_engine(self):
        """Reset all Engine state — heat map, connections, ticks. Clean slate."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            if not os.path.exists(db_path):
                return {"ok": True, "msg": "Engine already clean"}
            state = EngineState(db_path=db_path)
            conn = state._conn
            conn.execute("DELETE FROM heat_map")
            conn.execute("DELETE FROM connections")
            conn.execute("DELETE FROM memory_meta")
            conn.execute("UPDATE ticks SET count = 0 WHERE key = 'global'")
            conn.commit()
            return {"ok": True, "msg": "Engine reset — heat, connections, and metadata cleared"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def toggle_cli_ignore(self, ai_id):
        """Toggle heat ignore for a specific CLI."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            state = EngineState(db_path=db_path)
            current = state.get_config(f"heat_ignore_{ai_id}", "false")
            new_val = "false" if current == "true" else "true"
            state.set_config(f"heat_ignore_{ai_id}", new_val)
            return {"ok": True, "ignored": new_val == "true"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def toggle_collection(self, col_name):
        """Toggle whether a collection is included in Engine-backed retrieval."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            state = EngineState(db_path=db_path)
            current = state.get_config(f"collection_disabled_{col_name}", "false")
            new_val = "false" if current == "true" else "true"
            state.set_config(f"collection_disabled_{col_name}", new_val)
            return {"ok": True, "disabled": new_val == "true"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def rename_collection_label(self, col_name, new_label):
        """Set a custom display label for a collection."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            state = EngineState(db_path=db_path)
            state.set_config(f"collection_label_{col_name}", new_label)
            return {"ok": True, "msg": f"Renamed to '{new_label}'"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def get_collection_labels(self):
        """Get all custom collection labels."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            if not os.path.exists(db_path):
                return {"ok": True, "labels": {}}
            state = EngineState(db_path=db_path)
            conn = state._conn
            rows = conn.execute(
                "SELECT key, value FROM config WHERE key LIKE 'collection_label_%'"
            ).fetchall()
            labels = {}
            for row in rows:
                col_name = row["key"].replace("collection_label_", "", 1)
                labels[col_name] = row["value"]
            return {"ok": True, "labels": labels}
        except Exception as e:
            return {"ok": False, "labels": {}, "msg": str(e)}

    def get_collection_states(self):
        """Get disabled states for all collections."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            if not os.path.exists(db_path):
                return {"ok": True, "disabled": {}}
            state = EngineState(db_path=db_path)
            conn = state._conn
            rows = conn.execute(
                "SELECT key, value FROM config WHERE key LIKE 'collection_disabled_%'"
            ).fetchall()
            disabled = {}
            for row in rows:
                col_name = row["key"].replace("collection_disabled_", "", 1)
                disabled[col_name] = row["value"] == "true"
            return {"ok": True, "disabled": disabled}
        except Exception as e:
            return {"ok": False, "disabled": {}, "msg": str(e)}

    def detect_clis(self):
        """Detect which AI CLIs are installed."""
        clis = {}
        for name, binary in [("claude", "claude"), ("gemini", "gemini"), ("codex", "codex")]:
            path = shutil.which(binary)
            clis[name] = {"installed": path is not None, "path": path or ""}
        return {"ok": True, "clis": clis}

    def test_query(self, query, limit=5):
        """Run a full Engine-scored retrieval — same path as the hook uses."""
        try:
            from ember_memory.core.search import retrieve
            from ember_memory.core.embeddings.loader import get_embedding_provider
            from ember_memory.core.backends.loader import get_backend_v2
            import time

            cfg = load_config()
            embedder = get_embedding_provider()
            backend = get_backend_v2()
            engine_db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")

            t0 = time.monotonic()
            results = retrieve(
                prompt=query,
                ai_id="claude",
                backend=backend,
                embedder=embedder,
                limit=limit,
                similarity_threshold=float(cfg.get("similarity_threshold", "0.45")),
                engine_db_path=engine_db_path if os.path.exists(engine_db_path) else None,
            )
            elapsed = int((time.monotonic() - t0) * 1000)

            return {
                "ok": True,
                "elapsed_ms": elapsed,
                "results": [
                    {
                        "collection": r.collection,
                        "content": r.content,
                        "similarity": round(r.similarity, 4),
                        "composite_score": round(r.composite_score, 4),
                        "score_breakdown": r.score_breakdown,
                        "id": r.id[:32],
                    }
                    for r in results
                ],
            }
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def search_collection(self, collection, query, limit=5):
        """Search within a specific collection."""
        try:
            from ember_memory.core.embeddings.loader import get_embedding_provider
            from ember_memory.core.backends.loader import get_backend_v2
            embedder = get_embedding_provider()
            backend = get_backend_v2()
            embedding = embedder.embed(query)
            results = backend.search(collection, embedding, limit=limit)
            return {"ok": True, "results": results}
        except Exception as e:
            return {"ok": False, "msg": str(e)}


# ── HTML Frontend ────────────────────────────────────────────────────────────

HTML = open(os.path.join(EMBER_ROOT, "ui.html"), "r").read() if os.path.exists(
    os.path.join(EMBER_ROOT, "ui.html")) else "<html><body><h1>Missing ui.html</h1></body></html>"


# ── Launch ───────────────────────────────────────────────────────────────────

def main():
    try:
        import webview
    except ImportError:
        print("pywebview not installed. Run: pip install pywebview")
        sys.exit(1)

    api = EmberAPI()
    icon_path = os.path.join(EMBER_ROOT, "icons", "ember-memory.png")
    window = webview.create_window(
        "Ember Memory",
        html=HTML,
        js_api=api,
        width=840,
        height=660,
        min_size=(700, 550),
        background_color="#050505",
        text_select=False,
    )
    webview.start(debug=False, icon=icon_path)


if __name__ == "__main__":
    main()
