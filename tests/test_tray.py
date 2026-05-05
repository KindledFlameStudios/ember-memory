"""Tests for system tray process ownership helpers."""

from pathlib import Path

import controller.tray as tray


class FakeProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.waited = True
        return 0

    def kill(self):
        self.killed = True


def test_open_controller_tracks_process_and_prevents_duplicate(monkeypatch):
    tray._controller_processes.clear()
    calls = []

    def fake_which(name):
        if name == "ember-memory-controller":
            return "/tmp/ember/bin/ember-memory-controller"
        return None

    def fake_popen(command, **kwargs):
        proc = FakeProcess()
        calls.append((command, kwargs, proc))
        return proc

    monkeypatch.setattr(tray.shutil, "which", fake_which)
    monkeypatch.setattr(tray.subprocess, "Popen", fake_popen)

    try:
        first = tray._open_controller()
        second = tray._open_controller()

        assert first is second
        assert len(calls) == 1
        command, kwargs, _proc = calls[0]
        assert command == ["/tmp/ember/bin/ember-memory-controller"]
        assert kwargs["cwd"] == str(Path.home())
        assert kwargs["env"]["EMBER_FROM_TRAY"] == "1"
        assert kwargs["stdin"] is tray.subprocess.DEVNULL
        assert kwargs["stdout"] is tray.subprocess.DEVNULL
        assert kwargs["stderr"] is tray.subprocess.DEVNULL
    finally:
        tray._controller_processes.clear()


def test_terminate_controller_processes_closes_tracked_controllers():
    proc = FakeProcess()
    tray._controller_processes[:] = [proc]

    tray._terminate_controller_processes()

    assert proc.terminated is True
    assert proc.waited is True
    assert proc.killed is False
    assert tray._controller_processes == []
