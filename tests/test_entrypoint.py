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


class DummyLog:
    def __init__(self):
        self.closed = False

    def write(self, value):
        return len(value)

    def flush(self):
        return None

    def close(self):
        self.closed = True
