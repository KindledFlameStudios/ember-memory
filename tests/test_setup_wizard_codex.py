"""Tests for Codex installation wiring in the setup wizard."""

import json
from pathlib import Path
import sys
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import setup_wizard


def _patch_paths(monkeypatch, tmp_path):
    config_home = tmp_path / ".ember-memory"
    data_dir = tmp_path / "ember-data"

    monkeypatch.setattr(setup_wizard, "DEFAULT_DATA_DIR", str(data_dir))
    monkeypatch.setattr(setup_wizard, "CONFIG_HOME", str(config_home))
    monkeypatch.setattr(setup_wizard, "CONFIG_FILE", str(config_home / "config.env"))
    monkeypatch.setattr(setup_wizard, "CLAUDE_JSON", str(tmp_path / ".claude.json"))
    monkeypatch.setattr(setup_wizard, "CLAUDE_SETTINGS", str(tmp_path / ".claude" / "settings.json"))
    monkeypatch.setattr(setup_wizard, "GEMINI_SETTINGS", str(tmp_path / ".gemini" / "settings.json"))
    monkeypatch.setattr(setup_wizard, "CODEX_CONFIG", str(tmp_path / ".codex" / "config.toml"))
    monkeypatch.setattr(setup_wizard, "CODEX_HOOKS", str(tmp_path / ".codex" / "hooks.json"))
    monkeypatch.setattr(setup_wizard, "EMBER_ROOT", "/tmp/ember-memory-src")
    monkeypatch.setattr(setup_wizard.sys, "executable", "/usr/bin/python3")

    return data_dir


def test_write_codex_config_writes_expected_mcp_server(monkeypatch, tmp_path):
    data_dir = _patch_paths(monkeypatch, tmp_path)

    setup_wizard._write_codex_config(str(data_dir))

    with open(setup_wizard.CODEX_CONFIG, "rb") as f:
        config = tomllib.load(f)

    server = config["mcp_servers"]["ember-memory"]
    assert server["command"] == "/usr/bin/python3"
    assert server["args"] == [
        "-c",
        "import sys; sys.path.insert(0, '/tmp/ember-memory-src'); "
        "from ember_memory.server import mcp; mcp.run(transport='stdio')",
    ]
    assert server["startup_timeout_sec"] == 15
    assert server["tool_timeout_sec"] == 30
    assert server["env"] == {
        "EMBER_AI_ID": "codex",
        "EMBER_DATA_DIR": str(data_dir),
    }
    assert config["features"]["codex_hooks"] is True


def test_write_codex_hooks_writes_user_prompt_submit_handler(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)

    setup_wizard._write_codex_hooks()

    with open(setup_wizard.CODEX_HOOKS, "r") as f:
        hooks = json.load(f)

    user_prompt_submit = hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    assert user_prompt_submit["type"] == "command"
    assert user_prompt_submit["command"] == "/usr/bin/python3 /tmp/ember-memory-src/integrations/codex/hook.py"
    assert user_prompt_submit["timeout"] == 10
    assert "Ember Memory" in user_prompt_submit["statusMessage"]


def test_run_install_wires_codex_when_binary_exists(monkeypatch, tmp_path):
    data_dir = _patch_paths(monkeypatch, tmp_path)

    def fake_which(name):
        if name == "codex":
            return "/usr/bin/codex"
        return None

    monkeypatch.setattr(setup_wizard.shutil, "which", fake_which)

    result = setup_wizard.EmberAPI().run_install()

    assert result["ok"] is True
    assert Path(setup_wizard.CONFIG_FILE).exists()
    assert Path(setup_wizard.CODEX_CONFIG).exists()
    assert Path(setup_wizard.CODEX_HOOKS).exists()

    with open(setup_wizard.CODEX_CONFIG, "rb") as f:
        config = tomllib.load(f)

    assert config["mcp_servers"]["ember-memory"]["env"]["EMBER_DATA_DIR"] == str(data_dir)
    assert config["features"]["codex_hooks"] is True

    with open(setup_wizard.CODEX_HOOKS, "r") as f:
        hooks = json.load(f)

    assert hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"].endswith(
        "/integrations/codex/hook.py"
    )


def test_run_install_wires_gemini_mcp_with_namespace_env(monkeypatch, tmp_path):
    data_dir = _patch_paths(monkeypatch, tmp_path)

    def fake_which(name):
        if name == "gemini":
            return "/usr/bin/gemini"
        return None

    monkeypatch.setattr(setup_wizard.shutil, "which", fake_which)

    result = setup_wizard.EmberAPI().run_install()

    assert result["ok"] is True
    with open(setup_wizard.GEMINI_SETTINGS, "r") as f:
        settings = json.load(f)

    server = settings["mcpServers"]["ember-memory"]
    assert server["command"] == "/usr/bin/python3"
    assert server["args"] == [
        "-c",
        "import sys; sys.path.insert(0, '/tmp/ember-memory-src'); "
        "from ember_memory.server import mcp; mcp.run(transport='stdio')",
    ]
    assert server["env"] == {
        "EMBER_AI_ID": "gemini",
        "EMBER_DATA_DIR": str(data_dir),
    }

    hook = settings["hooks"]["BeforeAgent"][0]["hooks"][0]
    assert hook["command"] == "/usr/bin/python3 /tmp/ember-memory-src/integrations/gemini_cli/hook.py"


def test_check_integration_reports_codex_mcp(monkeypatch, tmp_path):
    data_dir = _patch_paths(monkeypatch, tmp_path)
    data_dir.mkdir(parents=True, exist_ok=True)

    cfg = setup_wizard.load_config()
    cfg["data_dir"] = str(data_dir)
    setup_wizard.save_config(cfg)
    setup_wizard._write_codex_config(str(data_dir))
    setup_wizard._write_codex_hooks()

    result = setup_wizard.EmberAPI().check_integration()

    assert result["config"] is True
    assert result["data_dir"] is True
    assert result["codex_mcp"] is True
    assert result["codex_hook"] is True
    assert result["mcp"] is True
    assert result["hook"] is True


def test_get_cli_from_session_maps_legacy_codex_uuid():
    assert setup_wizard._get_cli_from_session("019d543a-d11f-7421-b007-db86f14bd1a9") == "codex"
    assert setup_wizard._get_cli_from_session("codex-thread-123") == "codex"
