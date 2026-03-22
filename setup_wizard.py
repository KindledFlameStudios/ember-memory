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

    def save_settings(self, config):
        try:
            save_config(config)
            return {"ok": True, "msg": "Settings saved. Restart Claude Code to apply."}
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

        if errors:
            return {"ok": False, "msg": "; ".join(errors)}
        return {"ok": True, "msg": "Installed! Restart Claude Code to activate."}

    def get_collections(self):
        cfg = load_config()
        data_dir = cfg.get("data_dir", DEFAULT_DATA_DIR)
        if not os.path.isdir(data_dir):
            return {"ok": False, "collections": [], "msg": "Data directory not found"}

        try:
            import chromadb
            client = chromadb.PersistentClient(path=data_dir)
            collections = []
            for col_obj in client.list_collections():
                name = col_obj.name if hasattr(col_obj, 'name') else str(col_obj)
                col = client.get_collection(name)
                collections.append({"name": name, "count": col.count()})
            return {"ok": True, "collections": sorted(collections, key=lambda c: c["name"])}
        except ImportError:
            return {"ok": False, "collections": [], "msg": "ChromaDB not installed"}
        except Exception as e:
            return {"ok": False, "collections": [], "msg": str(e)}

    def create_collection(self, name):
        cfg = load_config()
        try:
            import chromadb
            from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
            client = chromadb.PersistentClient(path=cfg.get("data_dir", DEFAULT_DATA_DIR))
            ef = OllamaEmbeddingFunction(
                url=cfg.get("ollama_url", "http://localhost:11434/api/embeddings"),
                model_name=cfg.get("embedding_model", "bge-m3"))
            client.get_or_create_collection(name=name, embedding_function=ef,
                                             metadata={"hnsw:space": "cosine"})
            return {"ok": True, "msg": f"Collection '{name}' created"}
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

    def browse_directory(self):
        """Open native directory picker."""
        import webview
        result = webview.windows[0].create_file_dialog(
            webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            return {"ok": True, "path": result[0]}
        return {"ok": False, "path": ""}


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
