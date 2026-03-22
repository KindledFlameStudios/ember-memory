#!/usr/bin/env python3
"""
Ember Memory — Setup Script
=============================
Interactive setup that configures everything needed for persistent AI memory.
Checks prerequisites, creates directories, registers MCP server, and wires the hook.

Usage:
    python scripts/setup.py          # Interactive setup
    python scripts/setup.py --check  # Just verify prerequisites
"""

import json
import os
import shutil
import subprocess
import sys

EMBER_DIR = os.path.expanduser("~/.ember-memory")
CLAUDE_JSON = os.path.expanduser("~/.claude.json")
CLAUDE_SETTINGS = os.path.expanduser("~/.claude/settings.json")


def print_step(n, total, msg):
    print(f"\n[{n}/{total}] {msg}")


def print_ok(msg):
    print(f"  + {msg}")


def print_warn(msg):
    print(f"  ! {msg}")


def print_fail(msg):
    print(f"  x {msg}")


def check_ollama():
    """Check if Ollama is installed and running."""
    if not shutil.which("ollama"):
        return False, "Ollama not found. Install from https://ollama.com"

    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return False, "Ollama installed but not running. Start with: ollama serve"
        return True, result.stdout
    except subprocess.TimeoutExpired:
        return False, "Ollama not responding. Start with: ollama serve"
    except Exception as e:
        return False, f"Error checking Ollama: {e}"


def check_model(model_name="bge-m3"):
    """Check if the embedding model is pulled."""
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5
        )
        return model_name in result.stdout
    except Exception:
        return False


def check_python_deps():
    """Check required Python packages."""
    missing = []
    for pkg in ["chromadb", "mcp"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    return missing


def find_ember_memory_root():
    """Find the ember-memory package directory."""
    # Check if we're running from the repo
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    if os.path.exists(os.path.join(repo_root, "ember_memory", "server.py")):
        return repo_root
    return None


def register_mcp_server(ember_root: str, python_path: str):
    """Register the MCP server in Claude Code's config."""
    server_path = os.path.join(ember_root, "ember_memory", "server.py")

    # Read existing config
    config = {}
    if os.path.exists(CLAUDE_JSON):
        with open(CLAUDE_JSON, 'r') as f:
            config = json.load(f)

    if "mcpServers" not in config:
        config["mcpServers"] = {}

    config["mcpServers"]["ember-memory"] = {
        "command": python_path,
        "args": [server_path],
        "env": {
            "EMBER_DATA_DIR": EMBER_DIR,
        }
    }

    with open(CLAUDE_JSON, 'w') as f:
        json.dump(config, f, indent=2)

    return True


def register_hook(ember_root: str, python_path: str):
    """Register the auto-retrieval hook in Claude Code settings."""
    hook_path = os.path.join(ember_root, "ember_memory", "hook.py")

    # Read existing settings
    settings = {}
    os.makedirs(os.path.dirname(CLAUDE_SETTINGS), exist_ok=True)
    if os.path.exists(CLAUDE_SETTINGS):
        with open(CLAUDE_SETTINGS, 'r') as f:
            settings = json.load(f)

    if "hooks" not in settings:
        settings["hooks"] = {}

    hook_entry = {
        "type": "command",
        "command": f"{python_path} {hook_path}",
        "timeout": 10,
    }

    # Check if UserPromptSubmit already has hooks
    if "UserPromptSubmit" not in settings["hooks"]:
        settings["hooks"]["UserPromptSubmit"] = []

    # Check if we already registered
    existing_matchers = settings["hooks"]["UserPromptSubmit"]
    for entry in existing_matchers:
        if isinstance(entry, dict) and "hooks" in entry:
            for h in entry["hooks"]:
                if "ember" in h.get("command", "").lower():
                    print_ok("Hook already registered")
                    return True

    settings["hooks"]["UserPromptSubmit"].append({
        "matcher": "*",
        "hooks": [hook_entry],
    })

    with open(CLAUDE_SETTINGS, 'w') as f:
        json.dump(settings, f, indent=2)

    return True


def run_check():
    """Just check prerequisites without installing."""
    print("Ember Memory — Prerequisite Check\n")
    all_ok = True

    # Ollama
    ok, msg = check_ollama()
    if ok:
        print_ok("Ollama is running")
    else:
        print_fail(msg)
        all_ok = False

    # Model
    if ok:
        if check_model():
            print_ok("bge-m3 model available")
        else:
            print_warn("bge-m3 not pulled. Run: ollama pull bge-m3")
            all_ok = False

    # Python deps
    missing = check_python_deps()
    if missing:
        print_fail(f"Missing packages: {', '.join(missing)}")
        print(f"    Install with: pip install {' '.join(missing)}")
        all_ok = False
    else:
        print_ok("Python dependencies installed")

    # Data dir
    if os.path.exists(EMBER_DIR):
        print_ok(f"Data directory exists: {EMBER_DIR}")
    else:
        print_warn(f"Data directory not created: {EMBER_DIR}")

    print()
    if all_ok:
        print("All prerequisites met!")
    else:
        print("Some prerequisites missing — see above.")
    return all_ok


def run_setup():
    """Interactive setup flow."""
    print("=" * 50)
    print("  Ember Memory — Setup")
    print("  Persistent semantic memory for Claude Code")
    print("=" * 50)

    total_steps = 6

    # Step 1: Find ourselves
    print_step(1, total_steps, "Locating Ember Memory...")
    ember_root = find_ember_memory_root()
    if not ember_root:
        print_fail("Cannot find ember_memory package. Run setup from the repo directory.")
        sys.exit(1)
    print_ok(f"Found at: {ember_root}")

    # Step 2: Check Python
    print_step(2, total_steps, "Checking Python dependencies...")
    missing = check_python_deps()
    if missing:
        print_warn(f"Missing: {', '.join(missing)}")
        resp = input("  Install now? (Y/n): ").strip().lower()
        if resp != 'n':
            subprocess.run([sys.executable, "-m", "pip", "install"] + missing)
        else:
            print_fail("Cannot continue without dependencies.")
            sys.exit(1)
    print_ok("All Python dependencies available")

    # Step 3: Check Ollama
    print_step(3, total_steps, "Checking Ollama...")
    ok, msg = check_ollama()
    if not ok:
        print_fail(msg)
        print("  Ollama is required for local embeddings.")
        print("  Install: https://ollama.com")
        print("  Then: ollama serve && ollama pull bge-m3")
        sys.exit(1)
    print_ok("Ollama is running")

    if not check_model():
        print_warn("Pulling bge-m3 embedding model...")
        subprocess.run(["ollama", "pull", "bge-m3"])
        if not check_model():
            print_fail("Failed to pull bge-m3")
            sys.exit(1)
    print_ok("bge-m3 model ready")

    # Step 4: Create data directory
    print_step(4, total_steps, "Setting up data directory...")
    os.makedirs(EMBER_DIR, exist_ok=True)
    print_ok(f"Data directory: {EMBER_DIR}")

    # Step 5: Register MCP server
    print_step(5, total_steps, "Registering MCP server with Claude Code...")
    python_path = sys.executable
    register_mcp_server(ember_root, python_path)
    print_ok("MCP server registered in ~/.claude.json")

    # Step 6: Register hook
    print_step(6, total_steps, "Wiring auto-retrieval hook...")
    register_hook(ember_root, python_path)
    print_ok("Hook registered in Claude Code settings")

    print("\n" + "=" * 50)
    print("  Setup complete!")
    print("=" * 50)
    print()
    print("Next steps:")
    print("  1. Restart Claude Code to load the MCP server")
    print("  2. Ingest some content:")
    print(f"     python -m ember_memory.ingest /path/to/your/docs")
    print("  3. Start chatting — memories auto-retrieve on every message!")
    print()
    print("Configuration (environment variables):")
    print("  EMBER_DATA_DIR             — Storage location (default: ~/.ember-memory)")
    print("  EMBER_EMBEDDING_MODEL      — Ollama model (default: bge-m3)")
    print("  EMBER_SIMILARITY_THRESHOLD — Min match score (default: 0.45)")
    print("  EMBER_MAX_HOOK_RESULTS     — Results per message (default: 5)")
    print("  EMBER_HOOK_DEBUG           — Enable hook logging (default: false)")
    print()
    print("MCP tools available in Claude Code:")
    print("  memory_store, memory_find, memory_update, memory_delete")
    print("  list_collections, create_collection, delete_collection, collection_stats")


if __name__ == "__main__":
    if "--check" in sys.argv:
        run_check()
    else:
        run_setup()
