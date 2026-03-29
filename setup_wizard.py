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
import shutil
import subprocess
import sys
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
EMBER_ROOT = os.path.dirname(os.path.abspath(__file__))


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
        result = {"mcp": False, "hook": False, "data_dir": False, "config": False}

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
                    result["mcp"] = True
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
                                result["hook"] = True
            except Exception:
                pass

        return result

    def run_install(self):
        """Idempotent install: register MCP server + hook in CC config.

        Only touches CC config files once. All real settings live in config.env
        inside the data directory — the MCP server and hook read from there at
        runtime via ember_memory.config. CC config just gets a pointer.
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
                gemini_settings = os.path.expanduser("~/.gemini/settings.json")
                gemini_hook_path = os.path.join(EMBER_ROOT, "integrations", "gemini_cli", "hook.py")
                gs = {}
                if os.path.exists(gemini_settings):
                    with open(gemini_settings, 'r') as f:
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
                            "timeout": 3000
                        }]
                    })

                os.makedirs(os.path.dirname(gemini_settings), exist_ok=True)
                with open(gemini_settings, 'w') as f:
                    json.dump(gs, f, indent=2)
            except Exception as e:
                errors.append(f"Gemini CLI: {e}")

        if errors:
            return {"ok": False, "msg": "; ".join(errors)}
        return {"ok": True, "msg": "Installed! Restart Claude Code to activate."}

    def get_collections(self):
        """List all collections with counts — uses v2 backend."""
        try:
            from ember_memory.core.backends.loader import get_backend_v2
            backend = get_backend_v2()
            collections = backend.list_collections()
            return {"ok": True, "collections": sorted(collections, key=lambda c: c["name"])}
        except Exception as e:
            return {"ok": False, "collections": [], "msg": str(e)}

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

    def delete_collection(self, name):
        cfg = load_config()
        try:
            import chromadb
            client = chromadb.PersistentClient(path=cfg.get("data_dir", DEFAULT_DATA_DIR))
            client.delete_collection(name)
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

    def browse_directory(self):
        """Open native directory picker."""
        import webview
        result = webview.windows[0].create_file_dialog(
            webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            return {"ok": True, "path": result[0]}
        return {"ok": False, "path": ""}

    def get_engine_stats(self):
        """Get Ember Engine dashboard data."""
        try:
            from ember_memory.core.engine.state import EngineState
            from ember_memory.core.engine.stats import get_engine_stats
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
            return {"ok": True, "stats": get_engine_stats(state)}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def get_last_retrieval(self):
        """Get the most recent retrieval snapshot for the dashboard."""
        try:
            cfg = load_config()
            path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "last_retrieval.json")
            if not os.path.exists(path):
                return {"ok": True, "retrieval": None}
            with open(path, "r") as f:
                data = json.load(f)
            return {"ok": True, "retrieval": data}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def get_heat_map(self):
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
                "heat": state.get_all_heat(),
                "meta": state.get_all_memory_meta(),
            }
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def get_connections(self):
        """Get all connections for graph visualization."""
        try:
            from ember_memory.core.engine.state import EngineState
            cfg = load_config()
            db_path = os.path.join(cfg.get("data_dir", DEFAULT_DATA_DIR), "engine", "engine.db")
            if not os.path.exists(db_path):
                return {"ok": True, "connections": []}
            state = EngineState(db_path=db_path)
            conn = state._get_conn()
            rows = conn.execute(
                "SELECT id_a, id_b, strength FROM connections WHERE strength > 0.1 ORDER BY strength DESC LIMIT 100"
            ).fetchall()
            connections = [{"source": r[0], "target": r[1], "strength": r[2]} for r in rows]
            return {"ok": True, "connections": connections}
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
