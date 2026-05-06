"""Tests for controller installation wiring."""

import json
from pathlib import Path
import sys
import tomllib
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ember_memory.controller_app as controller_app


def test_normalize_ollama_url_accepts_base_and_api_paths():
    assert controller_app.normalize_ollama_url("http://localhost:11434") == (
        "http://localhost:11434/api/embeddings"
    )
    assert controller_app.normalize_ollama_url("http://localhost:11434/api/embed") == (
        "http://localhost:11434/api/embed"
    )
    assert controller_app.normalize_ollama_url("http://localhost:11434/api/embeddings") == (
        "http://localhost:11434/api/embeddings"
    )
    assert controller_app.normalize_ollama_url("http://localhost:11434/api/tags") == (
        "http://localhost:11434/api/embeddings"
    )


def test_load_config_migrates_legacy_threshold_fallback(monkeypatch, tmp_path):
    data_dir = _patch_paths(monkeypatch, tmp_path)
    Path(controller_app.CONFIG_HOME).mkdir(parents=True, exist_ok=True)
    Path(controller_app.CONFIG_FILE).write_text(
        "\n".join(
            [
                "EMBER_BACKEND=chromadb",
                f"EMBER_DATA_DIR={data_dir}",
                "EMBER_EMBEDDING_PROVIDER=ollama",
                "EMBER_EMBEDDING_MODEL=bge-m3",
                "EMBER_SIMILARITY_THRESHOLD=0.7",
            ]
        )
        + "\n"
    )

    cfg = controller_app.load_config()

    assert cfg["similarity_threshold"] == "0.45"


def _patch_paths(monkeypatch, tmp_path):
    config_home = tmp_path / ".ember-memory"
    data_dir = tmp_path / "ember-data"

    monkeypatch.setattr(controller_app, "DEFAULT_DATA_DIR", str(data_dir))
    monkeypatch.setattr(controller_app, "CONFIG_HOME", str(config_home))
    monkeypatch.setattr(controller_app, "CONFIG_FILE", str(config_home / "config.env"))
    monkeypatch.setattr(controller_app, "CLAUDE_JSON", str(tmp_path / ".claude.json"))
    monkeypatch.setattr(controller_app, "CLAUDE_SETTINGS", str(tmp_path / ".claude" / "settings.json"))
    monkeypatch.setattr(controller_app, "GEMINI_SETTINGS", str(tmp_path / ".gemini" / "settings.json"))
    monkeypatch.setattr(controller_app, "CODEX_CONFIG", str(tmp_path / ".codex" / "config.toml"))
    monkeypatch.setattr(controller_app, "CODEX_HOOKS", str(tmp_path / ".codex" / "hooks.json"))
    monkeypatch.setattr(controller_app, "EMBER_ROOT", "/tmp/ember-memory-src")
    monkeypatch.setattr(controller_app.sys, "executable", "/usr/bin/python3")

    return data_dir


def test_write_codex_config_writes_expected_mcp_server(monkeypatch, tmp_path):
    data_dir = _patch_paths(monkeypatch, tmp_path)

    controller_app._write_codex_config(str(data_dir))

    with open(controller_app.CODEX_CONFIG, "rb") as f:
        config = tomllib.load(f)

    server = config["mcp_servers"]["ember-memory"]
    assert server["command"] == "/usr/bin/python3"
    assert server["args"] == ["-m", "ember_memory.server"]
    assert server["startup_timeout_sec"] == 15
    assert server["tool_timeout_sec"] == 30
    assert server["env"] == {
        "EMBER_AI_ID": "codex",
        "EMBER_DATA_DIR": str(data_dir),
    }
    assert config["features"]["codex_hooks"] is True


def test_write_codex_hooks_writes_user_prompt_submit_handler(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller_app,
        "_script_path",
        lambda name: "/tmp/Ember Bin/ember-memory-codex-hook" if name == "ember-memory-codex-hook" else "",
    )

    controller_app._write_codex_hooks()

    with open(controller_app.CODEX_HOOKS, "r") as f:
        hooks = json.load(f)

    user_prompt_submit_entry = hooks["hooks"]["UserPromptSubmit"][0]
    user_prompt_submit = user_prompt_submit_entry["hooks"][0]
    assert user_prompt_submit_entry["matcher"] == "*"
    assert user_prompt_submit["name"] == "ember-memory"
    assert user_prompt_submit["type"] == "command"
    assert user_prompt_submit["command"] == "'/tmp/Ember Bin/ember-memory-codex-hook'"
    assert user_prompt_submit["timeout"] == 10
    assert "Ember Memory" in user_prompt_submit["statusMessage"]


def test_hook_command_strings_quote_paths_with_spaces(monkeypatch):
    monkeypatch.setattr(controller_app.platform, "system", lambda: "Linux")

    command = controller_app._command_string(
        "/tmp/Python Bin/python3",
        "/tmp/ember memory/integrations/codex/hook.py",
    )

    assert command == (
        "'/tmp/Python Bin/python3' "
        "'/tmp/ember memory/integrations/codex/hook.py'"
    )


def test_run_install_wires_codex_when_binary_exists(monkeypatch, tmp_path):
    data_dir = _patch_paths(monkeypatch, tmp_path)

    def fake_which(name):
        if name == "codex":
            return "/usr/bin/codex"
        if name == "ember-memory-codex-hook":
            return "/tmp/ember-memory-codex-hook"
        return None

    monkeypatch.setattr(controller_app.shutil, "which", fake_which)

    result = controller_app.EmberAPI().run_install()

    assert result["ok"] is True
    assert Path(controller_app.CONFIG_FILE).exists()
    assert Path(controller_app.CODEX_CONFIG).exists()
    assert Path(controller_app.CODEX_HOOKS).exists()

    with open(controller_app.CODEX_CONFIG, "rb") as f:
        config = tomllib.load(f)

    assert config["mcp_servers"]["ember-memory"]["env"]["EMBER_DATA_DIR"] == str(data_dir)
    assert config["features"]["codex_hooks"] is True

    with open(controller_app.CODEX_HOOKS, "r") as f:
        hooks = json.load(f)

    assert hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"].endswith(
        "ember-memory-codex-hook"
    )


def test_run_install_wires_claude_mcp_and_hook(monkeypatch, tmp_path):
    data_dir = _patch_paths(monkeypatch, tmp_path)

    def fake_which(name):
        if name == "ember-memory-claude-hook":
            return "/tmp/ember-memory-claude-hook"
        return None

    monkeypatch.setattr(controller_app.shutil, "which", fake_which)

    result = controller_app.EmberAPI().run_install()

    assert result["ok"] is True
    assert "Claude Code MCP" in result["installed"]
    assert "Claude Code hook" in result["installed"]

    with open(controller_app.CLAUDE_JSON, "r") as f:
        claude_config = json.load(f)

    server = claude_config["mcpServers"]["ember-memory"]
    assert server["command"] == "/usr/bin/python3"
    assert server["args"] == ["-m", "ember_memory.server"]
    assert server["env"] == {
        "EMBER_AI_ID": "claude",
        "EMBER_DATA_DIR": str(data_dir),
    }

    with open(controller_app.CLAUDE_SETTINGS, "r") as f:
        settings = json.load(f)

    hook = settings["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    assert hook["name"] == "ember-memory"
    assert hook["type"] == "command"
    assert hook["command"] == "/tmp/ember-memory-claude-hook"
    assert hook["timeout"] == 10


def test_run_hook_self_test_checks_all_fire_forge_hooks(monkeypatch, tmp_path):
    data_dir = _patch_paths(monkeypatch, tmp_path)
    cfg = controller_app.load_config()
    cfg["data_dir"] = str(data_dir)
    controller_app.save_config(cfg)

    def fake_script_command(script_name, fallback_module):
        return f"/tmp/bin/{script_name}", []

    calls = []

    def fake_run(command, input=None, text=None, capture_output=None, timeout=None, env=None, cwd=None):
        ai_id = env["EMBER_AI_ID"]
        calls.append((command, json.loads(input), ai_id))
        data_dir.mkdir(parents=True, exist_ok=True)
        with open(data_dir / "hook_invocations.jsonl", "a") as f:
            f.write(json.dumps({
                "hook": ai_id,
                "status": "no_results",
                "hits": 0,
            }) + "\n")
        stdout = "" if ai_id == "claude" else json.dumps({"continue": True})
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(controller_app, "_script_command", fake_script_command)
    monkeypatch.setattr(controller_app.subprocess, "run", fake_run)

    result = controller_app.EmberAPI().run_hook_self_test()

    assert result["ok"] is True
    assert [item["id"] for item in result["results"]] == ["claude", "gemini", "codex"]
    assert all(item["logged"] for item in result["results"])
    assert all(item["hook_status"] == "no_results" for item in result["results"])
    assert [call[2] for call in calls] == ["claude", "gemini", "codex"]


def test_run_install_wires_gemini_mcp_with_namespace_env(monkeypatch, tmp_path):
    data_dir = _patch_paths(monkeypatch, tmp_path)

    def fake_which(name):
        if name == "gemini":
            return "/usr/bin/gemini"
        if name == "ember-memory-gemini-hook":
            return "/tmp/ember-memory-gemini-hook"
        return None

    monkeypatch.setattr(controller_app.shutil, "which", fake_which)

    result = controller_app.EmberAPI().run_install()

    assert result["ok"] is True
    with open(controller_app.GEMINI_SETTINGS, "r") as f:
        settings = json.load(f)

    server = settings["mcpServers"]["ember-memory"]
    assert server["command"] == "/usr/bin/python3"
    assert server["args"] == ["-m", "ember_memory.server"]
    assert server["env"] == {
        "EMBER_AI_ID": "gemini",
        "EMBER_DATA_DIR": str(data_dir),
    }

    hook = settings["hooks"]["BeforeAgent"][0]["hooks"][0]
    assert hook["command"] == "/tmp/ember-memory-gemini-hook"


def test_run_install_wires_gemini_and_codex_without_cli_binaries_on_path(monkeypatch, tmp_path):
    data_dir = _patch_paths(monkeypatch, tmp_path)

    def fake_which(name):
        if name == "ember-memory-codex-hook":
            return "/tmp/ember-memory-codex-hook"
        if name == "ember-memory-gemini-hook":
            return "/tmp/ember-memory-gemini-hook"
        return None

    monkeypatch.setattr(controller_app.shutil, "which", fake_which)

    result = controller_app.EmberAPI().run_install()

    assert result["ok"] is True
    assert Path(controller_app.GEMINI_SETTINGS).exists()
    assert Path(controller_app.CODEX_CONFIG).exists()
    assert Path(controller_app.CODEX_HOOKS).exists()

    with open(controller_app.GEMINI_SETTINGS, "r") as f:
        gemini_settings = json.load(f)

    gemini_server = gemini_settings["mcpServers"]["ember-memory"]
    assert gemini_server["command"] == "/usr/bin/python3"
    assert gemini_server["args"] == ["-m", "ember_memory.server"]
    assert gemini_server["env"] == {
        "EMBER_AI_ID": "gemini",
        "EMBER_DATA_DIR": str(data_dir),
    }
    assert (
        gemini_settings["hooks"]["BeforeAgent"][0]["hooks"][0]["command"]
        == "/tmp/ember-memory-gemini-hook"
    )

    with open(controller_app.CODEX_CONFIG, "rb") as f:
        codex_config = tomllib.load(f)

    codex_server = codex_config["mcp_servers"]["ember-memory"]
    assert codex_server["command"] == "/usr/bin/python3"
    assert codex_server["args"] == ["-m", "ember_memory.server"]
    assert codex_server["env"] == {
        "EMBER_AI_ID": "codex",
        "EMBER_DATA_DIR": str(data_dir),
    }

    with open(controller_app.CODEX_HOOKS, "r") as f:
        codex_hooks = json.load(f)

    assert codex_hooks["hooks"]["UserPromptSubmit"][0]["matcher"] == "*"
    assert (
        codex_hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        == "/tmp/ember-memory-codex-hook"
    )


def test_check_integration_reports_codex_mcp(monkeypatch, tmp_path):
    data_dir = _patch_paths(monkeypatch, tmp_path)
    data_dir.mkdir(parents=True, exist_ok=True)

    cfg = controller_app.load_config()
    cfg["data_dir"] = str(data_dir)
    controller_app.save_config(cfg)
    controller_app._write_codex_config(str(data_dir))
    controller_app._write_codex_hooks()

    result = controller_app.EmberAPI().check_integration()

    assert result["config"] is True
    assert result["data_dir"] is True
    assert result["codex_mcp"] is True
    assert result["codex_hook"] is True
    assert result["mcp"] is True
    assert result["hook"] is True


def test_spawn_tray_process_detaches_from_terminal(monkeypatch):
    captured = {}
    log = DummyLog()

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(controller_app.sys, "executable", "/tmp/ember-env/bin/python")
    monkeypatch.setattr(controller_app.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(controller_app, "_open_launch_log", lambda name: log)

    controller_app._spawn_tray_process()

    assert captured["command"] == ["/tmp/ember-env/bin/python", "-m", "ember_memory", "tray"]
    assert captured["kwargs"]["cwd"] == str(Path.home())
    assert captured["kwargs"]["env"]["EMBER_TRAY_PROCESS"] == "1"
    assert captured["kwargs"]["stdin"] is controller_app.subprocess.DEVNULL
    assert captured["kwargs"]["stdout"] is log
    assert captured["kwargs"]["stderr"] is log
    assert log.closed is True
    if controller_app.os.name == "nt":
        assert "creationflags" in captured["kwargs"]
    else:
        assert captured["kwargs"]["start_new_session"] is True


def test_controller_main_exits_when_instance_lock_is_held(monkeypatch):
    calls = []

    monkeypatch.setattr(controller_app, "run_gui", lambda: calls.append("run_gui"))
    monkeypatch.setattr(
        "ember_memory.single_instance.acquire_instance_lock",
        lambda name: None,
    )

    controller_app.main()

    assert calls == []


def test_controller_main_closes_instance_lock(monkeypatch):
    calls = []
    lock = DummyLock()

    monkeypatch.setattr(controller_app, "run_gui", lambda: calls.append("run_gui"))
    monkeypatch.setattr(controller_app, "_spawn_tray_process", lambda: calls.append("tray"))
    monkeypatch.setattr(
        "ember_memory.single_instance.acquire_instance_lock",
        lambda name: lock,
    )

    controller_app.main()

    assert calls == ["run_gui", "tray"]
    assert lock.closed is True


def test_get_cli_from_session_maps_legacy_codex_uuid():
    assert controller_app._get_cli_from_session("019d543a-d11f-7421-b007-db86f14bd1a9") == "codex"
    assert controller_app._get_cli_from_session("codex-thread-123") == "codex"


def test_load_config_maps_max_preview_chars(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    Path(controller_app.CONFIG_HOME).mkdir(parents=True, exist_ok=True)
    Path(controller_app.CONFIG_FILE).write_text(
        "EMBER_MAX_PREVIEW_CHARS=321\n"
        "EMBER_BACKEND=chroma\n"
        "EMBER_OPENROUTER_API_KEY=sk-or-test\n"
    )

    cfg = controller_app.load_config()

    assert cfg["max_preview"] == "321"
    assert cfg["backend"] == "chromadb"
    assert cfg["openrouter_key"] == "sk-or-test"


def test_save_config_uses_current_google_embedding_default(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    cfg = controller_app.load_config()
    controller_app.save_config(cfg)

    saved = Path(controller_app.CONFIG_FILE).read_text()

    assert "EMBER_GOOGLE_EMBEDDING_MODEL=gemini-embedding-001" in saved


def test_load_config_migrates_legacy_provider_model(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    Path(controller_app.CONFIG_HOME).mkdir(parents=True, exist_ok=True)
    Path(controller_app.CONFIG_FILE).write_text(
        "EMBER_EMBEDDING_PROVIDER=google\n"
        "EMBER_EMBEDDING_MODEL=text-embedding-005\n"
    )

    cfg = controller_app.load_config()

    assert cfg["google_embedding_model"] == "text-embedding-005"


def test_controller_provider_models_uses_saved_provider_key(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    cfg = controller_app.load_config()
    cfg["openrouter_key"] = "sk-or-saved"
    controller_app.save_config(cfg)
    seen = {}

    def fake_get_provider_models(provider, api_key):
        seen["provider"] = provider
        seen["api_key"] = api_key
        return {"ok": True, "models": [{"id": "baai/bge-m3"}], "live": True}

    monkeypatch.setattr(
        "ember_memory.core.embeddings.model_catalog.get_provider_models",
        fake_get_provider_models,
    )

    result = controller_app.EmberAPI().get_provider_models("openrouter")

    assert result["ok"] is True
    assert seen == {"provider": "openrouter", "api_key": "sk-or-saved"}


def test_controller_provider_models_prefers_key_override(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    cfg = controller_app.load_config()
    cfg["openrouter_key"] = "sk-or-saved"
    controller_app.save_config(cfg)
    seen = {}

    def fake_get_provider_models(provider, api_key):
        seen["provider"] = provider
        seen["api_key"] = api_key
        return {"ok": True, "models": [{"id": "baai/bge-m3"}], "live": True}

    monkeypatch.setattr(
        "ember_memory.core.embeddings.model_catalog.get_provider_models",
        fake_get_provider_models,
    )

    result = controller_app.EmberAPI().get_provider_models("openrouter", "sk-or-unsaved")

    assert result["ok"] is True
    assert seen == {"provider": "openrouter", "api_key": "sk-or-unsaved"}


def test_open_external_url_allows_only_kfs(monkeypatch):
    opened = []

    monkeypatch.setattr(
        "webbrowser.open",
        lambda url: opened.append(url) or True,
    )

    api = controller_app.EmberAPI()

    assert api.open_external_url("https://kindledflamestudios.com")["ok"] is True
    assert api.open_external_url("https://example.com")["ok"] is False
    assert opened == ["https://kindledflamestudios.com"]


def test_custom_cli_registration_filters_dashboard_scopes(monkeypatch, tmp_path):
    data_dir = _patch_paths(monkeypatch, tmp_path)
    cfg = controller_app.load_config()
    cfg["data_dir"] = str(data_dir)
    controller_app.save_config(cfg)

    api = controller_app.EmberAPI()
    added = api.add_custom_cli("openclaw", "OpenClaw")

    assert added["ok"] is True
    assert controller_app._get_cli_from_session(
        "openclaw-session-1",
        cli_ids=controller_app.get_all_dashboard_ai_ids(),
    ) == "openclaw"
    assert api.add_custom_cli("codex", "Duplicate Base")["ok"] is False
    assert api.add_custom_cli("bad id", "Bad")["ok"] is False

    state = controller_app.get_engine_state(create=False)
    state.set_heat("mem-openclaw", 1.2, ai_id="openclaw-session-1")
    state.set_heat("mem-codex", 2.3, ai_id="codex-session-1")

    assert controller_app.get_dashboard_heat(state, ai_id="openclaw") == {"mem-openclaw": 1.2}


def test_dashboard_heat_filters_disabled_collections(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    state = controller_app.get_engine_state(create=True)
    state.set_heat("mem-archive", 2.0, ai_id="codex-thread-1")
    state.upsert_memory_meta("mem-archive", "archive", "Archive memory")

    assert controller_app.get_dashboard_heat(state, ai_id="codex") == {"mem-archive": 2.0}

    state.set_config("collection_disabled_archive", "true")

    assert controller_app.get_dashboard_heat(state, ai_id="codex") == {}


def test_get_last_retrieval_filters_disabled_results(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    data_dir = Path(controller_app.DEFAULT_DATA_DIR)
    engine_dir = data_dir / "engine"
    engine_dir.mkdir(parents=True, exist_ok=True)
    state = controller_app.get_engine_state(create=True)
    state.set_config("collection_disabled_archive", "true")

    retrieval_path = Path(controller_app.get_last_retrieval_path(str(data_dir), ai_id="codex"))
    retrieval_path.write_text(json.dumps({
        "ai_id": "codex",
        "results": [
            {"collection": "archive", "content": "disabled"},
            {"collection": "codex--identity", "content": "allowed"},
        ],
    }))

    api = controller_app.EmberAPI()
    result = api.get_last_retrieval("codex")

    assert result["ok"] is True
    assert result["retrieval"]["results"] == [
        {"collection": "codex--identity", "content": "allowed"},
    ]


def test_load_controller_html_injects_packaged_assets():
    html = controller_app.load_controller_html()

    assert "{{EMBER_UI_CSS}}" not in html
    assert "{{EMBER_UI_JS}}" not in html
    assert "EMBER MEMORY CONTROLLER v2" in html
    assert ".shell" in html


def test_load_controller_html_falls_back_to_installed_asset_dir(monkeypatch, tmp_path):
    asset_dir = tmp_path / "controller_assets"
    asset_dir.mkdir()
    (asset_dir / "ui.html").write_text(
        "<html><style>{{EMBER_UI_CSS}}</style><script>{{EMBER_UI_JS}}</script></html>",
        encoding="utf-8",
    )
    (asset_dir / "ui.css").write_text(".fallback { color: orange; }", encoding="utf-8")
    (asset_dir / "ui.js").write_text("window.fallback = true;", encoding="utf-8")

    monkeypatch.setattr(controller_app.resources, "files", lambda package: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(controller_app, "__file__", str(tmp_path / "controller_app.py"))

    html = controller_app.load_controller_html()

    assert "Missing controller UI assets" not in html
    assert ".fallback" in html
    assert "window.fallback = true" in html


class DummyLog:
    def __init__(self):
        self.closed = False

    def write(self, value):
        return len(value)

    def flush(self):
        return None

    def close(self):
        self.closed = True


class DummyLock:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True
