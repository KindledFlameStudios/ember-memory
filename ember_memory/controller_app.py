#!/usr/bin/env python3
"""
Ember Memory — Desktop Controller
=================================
Native desktop app for configuring, testing, and managing Ember Memory.
Uses pywebview for a native window with modern HTML/CSS frontend.

Run: python -m ember_memory
"""

import json
import logging
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
import ctypes.util
from datetime import datetime
from importlib import resources
from ember_memory.core.engine.scopes import (
    aggregate_heat_by_memory,
    get_all_cli_ids,
    get_disabled_collections,
    scope_to_cli,
)
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
EMBER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASHBOARD_AI_IDS_BASE = ["claude", "gemini", "codex"]

def get_all_dashboard_ai_ids(state=None):
    if not state:
        try:
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            if os.path.exists(db_path):
                from ember_memory.core.engine.state import EngineState
                state = EngineState(db_path=db_path)
        except Exception:
            return list(DASHBOARD_AI_IDS_BASE)
    return get_all_cli_ids(state)


def _normalize_custom_cli_id(cli_id):
    return str(cli_id or "").strip().lower()


def _validate_custom_cli_id(cli_id):
    if not re.match(r"^[a-z0-9][a-z0-9_-]*$", cli_id):
        return "CLI ID must use lowercase letters, numbers, dashes, or underscores"
    if cli_id in {"all", "shared", *DASHBOARD_AI_IDS_BASE}:
        return f"'{cli_id}' is reserved"
    return ""


def _load_custom_clis(state):
    try:
        clis = json.loads(state.get_config("custom_clis", "[]"))
    except Exception:
        return []
    if not isinstance(clis, list):
        return []
    return [
        {
            "id": _normalize_custom_cli_id(cli.get("id")),
            "name": str(cli.get("name") or cli.get("id") or "").strip(),
        }
        for cli in clis
        if isinstance(cli, dict) and _normalize_custom_cli_id(cli.get("id"))
    ]


def _shell_quote(value):
    text = str(value)
    text = text.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    return f'"{text}"'


def _command_string(*parts):
    values = [str(part) for part in parts]
    if platform.system() == "Windows":
        return subprocess.list2cmdline(values)
    return " ".join(shlex.quote(value) for value in values)


def _script_path(script_name):
    executable = shutil.which(script_name)
    if executable:
        return executable
    bin_dir = os.path.dirname(sys.executable)
    suffixes = [".exe", "-script.py", ".cmd", ".bat"] if platform.system() == "Windows" else [""]
    for suffix in suffixes:
        candidate = os.path.join(bin_dir, script_name + suffix)
        if os.path.exists(candidate):
            return candidate
    return ""


def _script_command(script_name, fallback_module):
    script = _script_path(script_name)
    if script:
        return script, []
    return sys.executable, ["-m", fallback_module]


def _script_command_string(script_name, fallback_module):
    command, args = _script_command(script_name, fallback_module)
    return _command_string(command, *args)


def _module_command(module_name):
    return sys.executable, ["-m", module_name]


def _module_command_string(module_name):
    return _command_string(sys.executable, "-m", module_name)


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _hook_self_test_specs():
    return [
        {
            "id": "claude",
            "label": "Claude Code",
            "script": "ember-memory-claude-hook",
            "module": "ember_memory.hook",
            "payload": {
                "prompt": "Ember Memory hook self test for Claude Code plumbing.",
                "hook_event_name": "UserPromptSubmit",
            },
            "expects_json": False,
        },
        {
            "id": "gemini",
            "label": "Gemini CLI",
            "script": "ember-memory-gemini-hook",
            "module": "ember_memory.gemini_hook",
            "payload": {
                "prompt": "Ember Memory hook self test for Gemini CLI plumbing.",
                "hook_event_name": "BeforeAgent",
                "session_id": "self-test",
            },
            "expects_json": True,
        },
        {
            "id": "codex",
            "label": "Codex",
            "script": "ember-memory-codex-hook",
            "module": "ember_memory.codex_hook",
            "payload": {
                "prompt": "Ember Memory hook self test for Codex plumbing.",
                "hook_event_name": "UserPromptSubmit",
                "session_id": "self-test",
                "cwd": os.getcwd(),
            },
            "expects_json": True,
        },
    ]


def _custom_cli_setup(cli_id):
    cfg = load_config()
    hook_bootstrap = (
        "import sys; "
        f"sys.path.insert(0, {EMBER_ROOT!r}); "
        "from ember_memory.hook_universal import main; "
        "main()"
    )
    mcp_bootstrap = (
        "import sys; "
        f"sys.path.insert(0, {EMBER_ROOT!r}); "
        "from ember_memory.server import mcp; "
        "mcp.run(transport='stdio')"
    )
    return {
        "hook_cmd": (
            f"EMBER_AI_ID={_shell_quote(cli_id)} "
            f"{_shell_quote(sys.executable)} -c {_shell_quote(hook_bootstrap)}"
        ),
        "mcp_config": json.dumps({
            "command": sys.executable,
            "args": ["-c", mcp_bootstrap],
            "env": {
                "EMBER_AI_ID": cli_id,
                "EMBER_DATA_DIR": cfg.get("data_dir", DEFAULT_DATA_DIR),
            },
        }, indent=2),
    }


def normalize_ollama_url(url):
    raw = str(url or "").strip() or "http://localhost:11434/api/embeddings"
    raw = raw.rstrip("/")
    if raw.endswith("/api/tags"):
        raw = raw[: -len("/api/tags")]
    if raw.endswith("/api/embed") or raw.endswith("/api/embeddings"):
        return raw
    return raw + "/api/embeddings"


def load_config():
    defaults = {
        "backend": "chromadb",
        "data_dir": DEFAULT_DATA_DIR,
        "embedding_provider": "ollama",
        "embedding_model": "bge-m3",
        "openai_embedding_model": "text-embedding-3-small",
        "google_embedding_model": "gemini-embedding-001",
        "openrouter_embedding_model": "baai/bge-m3",
        "ollama_url": "http://localhost:11434/api/embeddings",
        "openai_key": "",
        "google_key": "",
        "openrouter_key": "",
        "default_collection": "general",
        "similarity_threshold": "0.45",
        "max_results": "5",
        "max_preview": "800",
        "namespace_mode": "scoped",
        "auto_query": "true",
    }
    seen_keys = set()
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
                    elif key == "openai_api_key":
                        key = "openai_key"
                    elif key == "google_api_key":
                        key = "google_key"
                    elif key == "openrouter_api_key":
                        key = "openrouter_key"
                    seen_keys.add(key)
                    defaults[key] = val
    if defaults.get("backend") == "chroma":
        defaults["backend"] = "chromadb"
    elif defaults.get("backend") == "sqlite_vss":
        defaults["backend"] = "sqlite-vec"

    # v2 release-candidate builds briefly saved 0.7 from a UI fallback even
    # though the app default is 0.45. Treat that exact legacy value as the
    # intended default so test installs do not inherit an over-strict threshold.
    if defaults.get("similarity_threshold") == "0.7":
        defaults["similarity_threshold"] = "0.45"

    # Migrate old single-model config to provider-specific keys if needed.
    if "openai_embedding_model" not in seen_keys and defaults.get("embedding_provider") == "openai":
        defaults["openai_embedding_model"] = defaults.get("embedding_model", "text-embedding-3-small")
    if "google_embedding_model" not in seen_keys and defaults.get("embedding_provider") == "google":
        model = defaults.get("embedding_model", "")
        defaults["google_embedding_model"] = model if model and model != "bge-m3" else "gemini-embedding-001"
    if "openrouter_embedding_model" not in seen_keys and defaults.get("embedding_provider") == "openrouter":
        model = defaults.get("embedding_model", "")
        defaults["openrouter_embedding_model"] = model if model and model != "bge-m3" else "baai/bge-m3"

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
        f"EMBER_EMBEDDING_MODEL={config.get('embedding_model', 'bge-m3')}",
        f"EMBER_OPENAI_EMBEDDING_MODEL={config.get('openai_embedding_model', 'text-embedding-3-small')}",
        f"EMBER_GOOGLE_EMBEDDING_MODEL={config.get('google_embedding_model', 'gemini-embedding-001')}",
        f"EMBER_OPENROUTER_EMBEDDING_MODEL={config.get('openrouter_embedding_model', 'baai/bge-m3')}",
        f"EMBER_OLLAMA_URL={normalize_ollama_url(config['ollama_url'])}",
        f"EMBER_OPENAI_API_KEY={config.get('openai_key', '')}",
        f"EMBER_GOOGLE_API_KEY={config.get('google_key', '')}",
        f"EMBER_OPENROUTER_API_KEY={config.get('openrouter_key', '')}",
        f"EMBER_DEFAULT_COLLECTION={config['default_collection']}",
        f"EMBER_SIMILARITY_THRESHOLD={config['similarity_threshold']}",
        f"EMBER_MAX_HOOK_RESULTS={config['max_results']}",
        f"EMBER_MAX_PREVIEW_CHARS={config['max_preview']}",
        f"EMBER_NAMESPACE_MODE={config.get('namespace_mode', 'scoped')}",
        f"EMBER_AUTO_QUERY={config.get('auto_query', 'true')}",
    ]
    with open(CONFIG_FILE, 'w') as f:
        f.write("\n".join(lines) + "\n")


def _codex_server_command():
    """Return a stdio MCP launch command that works from wheel and source installs."""
    return _module_command("ember_memory.server")


def _source_server_command():
    """Return a generic stdio MCP launch command that works after installation."""
    return _module_command("ember_memory.server")


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
            if "integrations.codex.hook" in command:
                return True
    return False


def _write_codex_hooks():
    os.makedirs(os.path.dirname(CODEX_HOOKS), exist_ok=True)
    hook_cmd = _script_command_string("ember-memory-codex-hook", "ember_memory.codex_hook")
    hooks = {
        "hooks": {
            "UserPromptSubmit": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "name": "ember-memory",
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


def _get_cli_from_session(session_scope, cli_ids=None):
    """Map a session ID back to its parent CLI for dashboard aggregation.
    cc-12345 -> claude, gemini-98765 -> gemini, codex-555 -> codex"""
    return scope_to_cli(session_scope, cli_ids=cli_ids)


def _filter_retrieval_snapshot(state, retrieval):
    """Hide disabled collections from dashboard retrieval previews."""
    if not retrieval:
        return retrieval

    disabled = get_disabled_collections(state)
    results = [
        result
        for result in retrieval.get("results", [])
        if result.get("collection", "") not in disabled
    ]
    if len(results) == len(retrieval.get("results", [])):
        return retrieval
    return {**retrieval, "results": results}


def get_dashboard_heat(state, ai_id=None):
    return aggregate_heat_by_memory(state, ai_id=normalize_dashboard_ai_id(ai_id))


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

    def open_external_url(self, url):
        """Open a trusted external URL in the system browser."""
        try:
            import webbrowser
            url = str(url or "").strip()
            allowed = (
                "https://kindledflamestudios.com",
                "https://www.kindledflamestudios.com",
            )
            if not any(url == base or url.startswith(base + "/") for base in allowed):
                return {"ok": False, "msg": "External URL is not allowed"}
            return {"ok": bool(webbrowser.open(url)), "msg": "Opened browser"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def save_settings(self, incoming):
        try:
            # Merge incoming partial config with current config
            # so missing fields don't cause KeyErrors
            config = load_config()

            # Map UI field names to config keys (handle mismatches)
            field_map = {
                "openai_api_key": "openai_key",
                "google_api_key": "google_key",
                "openrouter_api_key": "openrouter_key",
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

    def get_tray_status(self):
        """Check if system tray is running."""
        try:
            # Check if pystray process is running
            import psutil
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = ' '.join(proc.info.get('cmdline', []) or [])
                    if 'ember-memory' in cmdline and 'tray' in cmdline:
                        return {"running": True, "pid": proc.info['pid']}
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return {"running": False, "pid": None}
        except ImportError:
            # psutil not installed, fallback to simple check
            return {"running": False, "pid": None, "msg": "psutil not installed"}
        except Exception as e:
            return {"running": False, "pid": None, "msg": str(e)}

    def launch_tray(self):
        """Launch the system tray application."""
        try:
            # Launch in background, detached from this process
            subprocess.Popen(
                [sys.executable, "-m", "controller"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return {"ok": True, "msg": "System tray launched"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def stop_tray(self):
        """Stop the system tray application."""
        try:
            import psutil
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = ' '.join(proc.info.get('cmdline', []) or [])
                    if 'ember-memory' in cmdline and 'tray' in cmdline:
                        proc.terminate()
                        return {"ok": True, "msg": f"System tray stopped (PID {proc.info['pid']})"}
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return {"ok": True, "msg": "System tray was not running"}
        except ImportError:
            return {"ok": False, "msg": "psutil not installed - cannot stop tray"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def get_desktop_launcher_status(self):
        """Check whether the OS desktop launcher is installed."""
        from ember_memory.desktop_integration import desktop_launcher_status
        return desktop_launcher_status()

    def install_desktop_launcher(self):
        """Install app menu / Start Menu launcher for Ember Memory."""
        from ember_memory.desktop_integration import install_desktop_launcher
        return install_desktop_launcher()

    def uninstall_desktop_launcher(self):
        """Remove app menu / Start Menu launcher for Ember Memory."""
        from ember_memory.desktop_integration import uninstall_desktop_launcher
        return uninstall_desktop_launcher()

    def run_install(self):
        """Idempotent install: register Ember Memory with supported local CLIs.

        All real settings live in config.env inside the data directory. CLI
        config files only get the launch pointers and hook wiring they need.
        """
        errors = []
        installed = []
        cfg = load_config()
        data_dir = cfg.get("data_dir", DEFAULT_DATA_DIR)

        # 1. Create data directory + save config.env
        try:
            os.makedirs(data_dir, exist_ok=True)
            save_config(cfg)
            installed.append("config.env")
        except Exception as e:
            errors.append(f"Data dir: {e}")

        # 2. MCP server — register in .claude.json (idempotent)
        try:
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
                "args": ["-m", "ember_memory.server"],
                "env": {
                    "EMBER_AI_ID": "claude",
                    "EMBER_DATA_DIR": data_dir,
                },
            }

            # Only write if missing or changed
            if existing != desired:
                config_data["mcpServers"]["ember-memory"] = desired
                with open(CLAUDE_JSON, 'w') as f:
                    json.dump(config_data, f, indent=2)
            installed.append("Claude Code MCP")
        except Exception as e:
            errors.append(f"MCP: {e}")

        # 3. Hook — register in settings.json (idempotent)
        try:
            python_path = sys.executable
            hook_cmd = _script_command_string("ember-memory-claude-hook", "ember_memory.hook")

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
                            h["name"] = "ember-memory"
                            h["type"] = "command"
                            h["command"] = hook_cmd
                            h["timeout"] = 10
                            found = True

            if not found:
                settings["hooks"]["UserPromptSubmit"].append({
                    "matcher": "*",
                    "hooks": [{
                        "name": "ember-memory",
                        "type": "command",
                        "command": hook_cmd,
                        "timeout": 10,
                    }],
                })

            with open(CLAUDE_SETTINGS, 'w') as f:
                json.dump(settings, f, indent=2)
            installed.append("Claude Code hook")
        except Exception as e:
            errors.append(f"Hook: {e}")

        # 4. Gemini CLI — register hook + MCP idempotently.
        try:
            gemini_command, gemini_args = _source_server_command()
            gs = {}
            if os.path.exists(GEMINI_SETTINGS):
                with open(GEMINI_SETTINGS, 'r') as f:
                    gs = json.load(f)

            # MCP server
            if "mcpServers" not in gs:
                gs["mcpServers"] = {}
            gs["mcpServers"]["ember-memory"] = {
                "command": gemini_command,
                "args": gemini_args,
                "env": {
                    "EMBER_AI_ID": "gemini",
                    "EMBER_DATA_DIR": data_dir,
                },
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
                            h["name"] = "ember-memory"
                            h["type"] = "command"
                            h["command"] = _script_command_string(
                                "ember-memory-gemini-hook",
                                "ember_memory.gemini_hook",
                            )
                            h["timeout"] = 10000
                            ember_exists = True

            if not ember_exists:
                gs["hooks"]["BeforeAgent"].append({
                    "matcher": "*",
                    "hooks": [{
                        "name": "ember-memory",
                        "type": "command",
                        "command": _script_command_string(
                            "ember-memory-gemini-hook",
                            "ember_memory.gemini_hook",
                        ),
                        "timeout": 10000
                    }]
                })

            os.makedirs(os.path.dirname(GEMINI_SETTINGS), exist_ok=True)
            with open(GEMINI_SETTINGS, 'w') as f:
                json.dump(gs, f, indent=2)
            installed.append("Gemini CLI MCP + hook")
        except Exception as e:
            errors.append(f"Gemini CLI: {e}")

        # 5. Codex — register MCP server + hook idempotently.
        try:
            _write_codex_config(data_dir)
            _write_codex_hooks()
            installed.append("Codex MCP + hook")
        except Exception as e:
            errors.append(f"Codex: {e}")

        if errors:
            return {"ok": False, "msg": "; ".join(errors), "installed": installed}
        return {
            "ok": True,
            "msg": "Installed: " + ", ".join(installed) + ". Restart your CLIs to activate.",
            "installed": installed,
            "data_dir": data_dir,
        }

    def run_hook_self_test(self):
        """Run installed hook commands directly and report plumbing health."""
        cfg = load_config()
        data_dir = cfg.get("data_dir", DEFAULT_DATA_DIR)
        os.makedirs(data_dir, exist_ok=True)
        invocation_path = os.path.join(data_dir, "hook_invocations.jsonl")
        before = _read_jsonl(invocation_path)
        before_len = len(before)
        results = []

        for spec in _hook_self_test_specs():
            command, args = _script_command(spec["script"], spec["module"])
            payload = json.dumps(spec["payload"])
            env = {
                **os.environ,
                "EMBER_AI_ID": spec["id"],
                "EMBER_DATA_DIR": data_dir,
            }
            result = {
                "id": spec["id"],
                "label": spec["label"],
                "command": _command_string(command, *args),
                "ok": False,
                "returncode": None,
                "stdout_valid": False,
                "logged": False,
                "hook_status": "",
                "hits": None,
                "msg": "",
            }
            try:
                proc = subprocess.run(
                    [command, *args],
                    input=payload,
                    text=True,
                    capture_output=True,
                    timeout=15,
                    env=env,
                    cwd=os.path.expanduser("~"),
                )
                result["returncode"] = proc.returncode
                stdout = (proc.stdout or "").strip()
                stderr = (proc.stderr or "").strip()
                if spec["expects_json"]:
                    try:
                        json.loads(stdout or "{}")
                        result["stdout_valid"] = True
                    except Exception:
                        result["stdout_valid"] = False
                else:
                    result["stdout_valid"] = proc.returncode == 0

                after = _read_jsonl(invocation_path)
                new_rows = after[before_len:]
                before_len = len(after)
                matching = [
                    row for row in new_rows
                    if str(row.get("hook", "")).lower() == spec["id"]
                ]
                if matching:
                    latest = matching[-1]
                    result["logged"] = True
                    result["hook_status"] = str(latest.get("status") or "")
                    if "hits" in latest:
                        result["hits"] = latest.get("hits")

                result["ok"] = (
                    proc.returncode == 0
                    and result["stdout_valid"]
                    and result["logged"]
                )
                if result["ok"]:
                    if result["hits"] is None:
                        result["msg"] = f"{spec['label']} hook ran and logged {result['hook_status'] or 'ok'}."
                    else:
                        result["msg"] = (
                            f"{spec['label']} hook ran and logged "
                            f"{result['hook_status'] or 'ok'} ({result['hits']} hits)."
                        )
                else:
                    details = []
                    if proc.returncode != 0:
                        details.append(f"exit {proc.returncode}")
                    if not result["stdout_valid"]:
                        details.append("invalid stdout")
                    if not result["logged"]:
                        details.append("no invocation log")
                    if stderr:
                        details.append(stderr[:160])
                    result["msg"] = f"{spec['label']} self-test incomplete: " + ", ".join(details)
            except Exception as e:
                result["msg"] = f"{spec['label']} self-test failed: {e}"

            results.append(result)

        ok = all(item["ok"] for item in results)
        return {
            "ok": ok,
            "results": results,
            "msg": "Hook self-test passed." if ok else "Hook self-test found issues.",
            "log_path": invocation_path,
        }

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
            url = normalize_ollama_url(cfg.get("ollama_url", "")).replace("/api/embeddings", "/api/tags").replace("/api/embed", "/api/tags")
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
            url = normalize_ollama_url(cfg.get("ollama_url", "")).replace("/api/embeddings", "/api/tags").replace("/api/embed", "/api/tags")
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

    def get_provider_models(self, provider, key_override=""):
        """Return available embedding models for a provider."""
        provider = str(provider or "").lower().strip()

        if provider == "ollama":
            return self.get_ollama_models()
        cfg = load_config()
        key_map = {"openai": "openai_key", "google": "google_key", "openrouter": "openrouter_key"}
        api_key = str(key_override or "").strip() or cfg.get(key_map.get(provider, ""), "")
        from ember_memory.core.embeddings.model_catalog import get_provider_models
        return get_provider_models(provider, api_key)

    # ── Key / connection verification ──────────────────────────────────────────

    def verify_provider_auth(self, provider, key_override=""):
        """Quickly verify a provider's API key works. Accepts optional key from UI input.
        If key_override is provided (from the text field), uses that directly.
        Otherwise reads from saved config."""
        provider = str(provider or "").lower().strip()
        key = str(key_override or "").strip()

        # If no key from UI, fall back to saved config
        if not key:
            cfg = load_config()
            key_map = {"openai": "openai_key", "google": "google_key", "openrouter": "openrouter_key"}
            key = cfg.get(key_map.get(provider, ""), "")
        if not key:
            return {"ok": False, "msg": "No API key provided"}

        if provider == "ollama":
            return self.test_ollama()

        from ember_memory.core.embeddings.model_catalog import verify_provider_auth
        result = verify_provider_auth(provider, key)
        if result.get("ok"):
            result["msg"] = "✓ " + result.get("msg", "Connected")
        else:
            result["msg"] = "✗ " + result.get("msg", "Failed")
        return result

    def verify_model(self, provider, model):
        """Verify a specific model exists and is accessible for the given provider."""
        provider = str(provider or "").lower().strip()
        model = str(model or "").strip()
        if not model:
            return {"ok": False, "msg": "No model specified"}

        if provider == "ollama":
            return {"ok": True, "msg": f"✓ {model}"}

        from ember_memory.core.embeddings.model_catalog import verify_model
        result = verify_model(provider, model)
        if result.get("ok"):
            result["msg"] = "✓ " + result.get("msg", "Ready")
        else:
            result["msg"] = "✗ " + result.get("msg", "Not validated")
        return result

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
                    "ignored_clis": {cli_id: False for cli_id in DASHBOARD_AI_IDS_BASE}
                }}
            state = EngineState(db_path=db_path)
            all_heat = get_dashboard_heat(state, ai_id=ai_id)
            hot_count = sum(1 for heat in all_heat.values() if heat >= 0.5)
            connection_rows = get_dashboard_connections(state, ai_id=ai_id, min_strength=0.0)
            total_connections = len(connection_rows)
            established = sum(1 for row in connection_rows if float(row["strength"]) >= 3.0)

            # For session-scoped views, count ALL memories ever touched (including decayed)
            total_tracked = len(all_heat)
            selected = normalize_dashboard_ai_id(ai_id)
            if selected and (selected.startswith("cc-") or selected.startswith("gemini-") or selected.startswith("codex-")):
                all_ever = state._conn.execute(
                    "SELECT COUNT(DISTINCT memory_id) FROM heat_map WHERE ai_id = ?",
                    (selected,),
                ).fetchone()[0]
                total_tracked = max(total_tracked, all_ever)

            return {"ok": True, "stats": {
                "tick_count": state.get_tick(),
                "total_memories_tracked": total_tracked,
                "hot_memories": hot_count,
                "total_connections": total_connections,
                "established_connections": established,
                "heat_mode": state.get_config("heat_mode", "universal"),
                "ignored_clis": {
                    cli_ai: state.get_config(f"heat_ignore_{cli_ai}", "false") == "true"
                    for cli_ai in get_all_dashboard_ai_ids(state)
                },
            }}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def get_last_retrieval(self, ai_id=None):
        """Get the most recent retrieval snapshot for the dashboard."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            data_dir = cfg.get("data_dir", DEFAULT_DATA_DIR)
            retrieval = read_json_file(get_last_retrieval_path(data_dir, ai_id=ai_id))
            if retrieval is None:
                return {"ok": True, "retrieval": None}
            db_path = os.path.join(data_dir, "engine", "engine.db")
            if os.path.exists(db_path):
                retrieval = _filter_retrieval_snapshot(EngineState(db_path=db_path), retrieval)
            return {"ok": True, "retrieval": retrieval}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def get_all_last_retrievals(self):
        """Get the global and per-AI retrieval snapshots for the dashboard."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            data_dir = cfg.get("data_dir", DEFAULT_DATA_DIR)
            state = None
            db_path = os.path.join(data_dir, "engine", "engine.db")
            if os.path.exists(db_path):
                state = EngineState(db_path=db_path)
            retrievals = {
                "all": read_json_file(get_last_retrieval_path(data_dir)),
            }
            for ai_id in get_all_dashboard_ai_ids():
                retrievals[ai_id] = read_json_file(get_last_retrieval_path(data_dir, ai_id=ai_id))
            if state is not None:
                retrievals = {
                    key: _filter_retrieval_snapshot(state, value)
                    for key, value in retrievals.items()
                }
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
            cli_ids = get_all_dashboard_ai_ids()
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
                            cli = _get_cli_from_session(sid, cli_ids=cli_ids)
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
        """Toggle basic-RAG mode for a specific CLI.

        When enabled, retrieval still works but adaptive Engine heat/scoring for
        that CLI is paused so parallel sessions do not keep amplifying a topic.
        """
        try:
            from ember_memory.core.engine.heat import HeatMap
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            state = EngineState(db_path=db_path)
            current = state.get_config(f"heat_ignore_{ai_id}", "false")
            new_val = "false" if current == "true" else "true"
            HeatMap(state).set_ignored(ai_id, new_val == "true")
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


    def get_custom_clis(self):
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            if not os.path.exists(db_path):
                return {"ok": True, "clis": []}
            state = EngineState(db_path=db_path)
            clis = _load_custom_clis(state)
            for cli in clis:
                cli.update(_custom_cli_setup(cli["id"]))
            return {"ok": True, "clis": clis}
        except Exception as e:
            return {"ok": False, "clis": [], "msg": str(e)}

    def add_custom_cli(self, cli_id, cli_name):
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            state = EngineState(db_path=db_path)

            cli_id = _normalize_custom_cli_id(cli_id)
            invalid = _validate_custom_cli_id(cli_id)
            if invalid:
                return {"ok": False, "msg": invalid}
            cli_name = str(cli_name or "").strip() or cli_id

            clis = _load_custom_clis(state)
            # Check if exists
            for c in clis:
                if c["id"] == cli_id:
                    return {"ok": False, "msg": f"CLI '{cli_id}' already exists"}
            clis.append({"id": cli_id, "name": cli_name})
            state.set_config("custom_clis", json.dumps(clis))

            setup = _custom_cli_setup(cli_id)

            return {
                "ok": True,
                "msg": f"Added {cli_name} ({cli_id})",
                "cli_id": cli_id,
                **setup,
            }
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def remove_custom_cli(self, cli_id):
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            if not os.path.exists(db_path):
                return {"ok": False, "msg": "DB not found"}
            state = EngineState(db_path=db_path)

            cli_id = _normalize_custom_cli_id(cli_id)
            clis = _load_custom_clis(state)
            clis = [c for c in clis if c["id"] != cli_id]
            state.set_config("custom_clis", json.dumps(clis))
            return {"ok": True, "msg": f"Removed {cli_id}"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

# ── HTML Frontend ────────────────────────────────────────────────────────────

def load_controller_html():
    """Load the controller shell and inject local CSS/JS assets."""
    try:
        asset_root = resources.files("ember_memory.controller_assets")
        html = asset_root.joinpath("ui.html").read_text()
        css = asset_root.joinpath("ui.css").read_text()
        js = asset_root.joinpath("ui.js").read_text()
    except Exception:
        html_path = os.path.join(EMBER_ROOT, "ui.html")
        css_path = os.path.join(EMBER_ROOT, "ui.css")
        js_path = os.path.join(EMBER_ROOT, "ui.js")
        if not os.path.exists(html_path):
            return "<html><body><h1>Missing controller UI assets</h1></body></html>"
        with open(html_path, "r") as f:
            html = f.read()
        css = ""
        js = ""
        if os.path.exists(css_path):
            with open(css_path, "r") as f:
                css = f.read()
        if os.path.exists(js_path):
            with open(js_path, "r") as f:
                js = f.read()

    if "{{EMBER_UI_CSS}}" not in html or "{{EMBER_UI_JS}}" not in html:
        return "<html><body><h1>Missing ui.html</h1></body></html>"
    return html.replace("{{EMBER_UI_CSS}}", css).replace("{{EMBER_UI_JS}}", js)


# ── Launch ───────────────────────────────────────────────────────────────────


def _linux_gui_preflight():
    """Fail early with an actionable message for common Linux Qt backend gaps."""
    if platform.system() != "Linux":
        return None

    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
        return "qt"

    if os.environ.get("QT_QPA_PLATFORM"):
        return "qt"

    try:
        import gi  # noqa: F401
        return None
    except Exception:
        pass

    if ctypes.util.find_library("xcb-cursor") is None:
        print(
            "Ember Memory needs the Qt xcb cursor system library to open the controller on Linux.\n\n"
            "Install one of these, then launch Ember Memory again:\n"
            "  Ubuntu/Debian: sudo apt install libxcb-cursor0\n"
            "  Fedora:        sudo dnf install xcb-util-cursor\n"
            "  Arch:          sudo pacman -S xcb-util-cursor\n",
            file=sys.stderr,
        )
        sys.exit(1)

    current_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--disable-gpu" not in current_flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (current_flags + " --disable-gpu").strip()
    return "qt"


def run_gui():
    """Create and start the webview window. Returns when window is closed."""
    gui = _linux_gui_preflight()
    try:
        import webview
    except ImportError:
        print("pywebview not installed. Run: pip install pywebview")
        sys.exit(1)

    from ember_memory.desktop_integration import get_icon_path

    api = EmberAPI()
    icon_path = get_icon_path()
    window = webview.create_window(
        "Ember Memory",
        html=load_controller_html(),
        js_api=api,
        width=840,
        height=660,
        min_size=(700, 550),
        background_color="#050505",
        text_select=True,
    )
    start_kwargs = {"debug": False}
    if gui:
        start_kwargs["gui"] = gui
    if icon_path:
        start_kwargs["icon"] = icon_path
    webview.start(**start_kwargs)


def _spawn_tray_process():
    """Launch the tray in a detached process so terminal launches can exit."""
    env = {**os.environ, "EMBER_TRAY_PROCESS": "1"}
    command = [sys.executable, "-m", "ember_memory", "tray"]
    popen_kwargs = {
        "cwd": os.path.expanduser("~"),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    return subprocess.Popen(command, **popen_kwargs)


def main():
    """Launch the GUI controller. When window is closed, minimize to tray.
    The tray provides quick controls and the option to reopen the GUI or quit.
    """
    # Show the GUI first
    run_gui()

    # If launched from an existing tray (via "Open Controller"), just exit.
    # The original process keeps the tray alive.
    if os.environ.get("EMBER_FROM_TRAY") == "1":
        return

    # User closed the window — keep background controls available from a
    # detached tray process while allowing terminal launches to return.
    try:
        _spawn_tray_process()
    except Exception:
        return


if __name__ == "__main__":
    main()
