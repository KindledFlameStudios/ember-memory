"""Tests for Ember Memory command entry points."""

from pathlib import Path

import ember_memory.__main__ as entrypoint


def test_launch_app_detached_returns_immediately(monkeypatch):
    captured = {}
    log = DummyLog()

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(entrypoint.sys, "executable", "/tmp/ember-env/bin/python")
    monkeypatch.setattr(entrypoint.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(entrypoint, "_open_launch_log", lambda name: log)

    entrypoint.launch_app_detached()

    assert captured["command"] == ["/tmp/ember-env/bin/python", "-m", "ember_memory", "controller"]
    assert captured["kwargs"]["cwd"] == str(Path.home())
    assert captured["kwargs"]["env"]["EMBER_APP_LAUNCHER"] == "1"
    assert captured["kwargs"]["stdin"] is entrypoint.subprocess.DEVNULL
    assert captured["kwargs"]["stdout"] is log
    assert captured["kwargs"]["stderr"] is log
    assert log.closed is True
    if entrypoint.os.name == "nt":
        assert "creationflags" in captured["kwargs"]
    else:
        assert captured["kwargs"]["start_new_session"] is True


def test_default_command_uses_detached_app_launcher(monkeypatch):
    calls = []

    monkeypatch.setattr(entrypoint.sys, "argv", ["ember-memory"])
    monkeypatch.setattr(entrypoint, "launch_app_detached", lambda: calls.append("launch"))

    entrypoint.main()

    assert calls == ["launch"]


def test_controller_command_uses_foreground_controller(monkeypatch):
    calls = []

    monkeypatch.setattr(entrypoint.sys, "argv", ["ember-memory", "controller"])
    monkeypatch.setattr(entrypoint, "launch_controller", lambda: calls.append("controller"))

    entrypoint.main()

    assert calls == ["controller"]


def test_uninstall_command_removes_launcher_and_preserves_data_by_default(monkeypatch, tmp_path, capsys):
    removed = []
    data_dir = tmp_path / "home" / ".ember-memory"
    data_dir.mkdir(parents=True)

    monkeypatch.setattr(entrypoint.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(entrypoint.sys, "executable", "/tmp/ember-env/bin/python")

    def fake_uninstall():
        removed.append("launcher")
        return {"ok": True, "platform": "linux", "removed": ["/tmp/launcher"]}

    monkeypatch.setattr(
        "ember_memory.desktop_integration.uninstall_desktop_launcher",
        fake_uninstall,
    )
    monkeypatch.setattr(
        "ember_memory.desktop_integration.format_result",
        lambda result: "formatted-result",
    )

    entrypoint.print_uninstall_result()

    output = capsys.readouterr().out
    assert removed == ["launcher"]
    assert data_dir.exists()
    assert "formatted-result" in output
    assert "/tmp/ember-env/bin/python -m pip uninstall -y ember-memory" in output
    assert "Local memories and settings are preserved" in output


def test_uninstall_command_can_delete_data(monkeypatch, tmp_path, capsys):
    data_dir = tmp_path / "home" / ".ember-memory"
    data_dir.mkdir(parents=True)

    monkeypatch.setattr(entrypoint.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(
        "ember_memory.desktop_integration.uninstall_desktop_launcher",
        lambda: {"ok": True, "platform": "linux", "removed": []},
    )
    monkeypatch.setattr(
        "ember_memory.desktop_integration.format_result",
        lambda result: "formatted-result",
    )

    entrypoint.print_uninstall_result(delete_data=True)

    output = capsys.readouterr().out
    assert not data_dir.exists()
    assert "Deleted local Ember Memory data" in output


def test_update_command_prints_safe_update_options(monkeypatch, capsys):
    monkeypatch.setattr(entrypoint.sys, "executable", "/tmp/ember-env/bin/python")

    entrypoint.print_update_result()

    output = capsys.readouterr().out
    assert "Ember Memory update" in output
    assert f"/tmp/ember-env/bin/python -m pip install --upgrade {entrypoint.PACKAGE_URL}" in output
    assert "/tmp/ember-env/bin/python -m pip install --upgrade --no-deps" in output
    assert entrypoint.PACKAGE_URL in output
    assert "Avoid --force-reinstall" in output


class DummyLog:
    def __init__(self):
        self.closed = False

    def write(self, value):
        return len(value)

    def flush(self):
        return None

    def close(self):
        self.closed = True
