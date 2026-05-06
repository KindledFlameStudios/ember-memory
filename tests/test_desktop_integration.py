from pathlib import Path

from ember_memory import desktop_integration


def test_linux_launcher_install_and_uninstall(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(desktop_integration.platform, "system", lambda: "Linux")
    monkeypatch.setattr(desktop_integration, "_controller_command", lambda: ["/tmp/Ember Bin/ember-memory-controller"])
    monkeypatch.setattr(desktop_integration.shutil, "which", lambda name: None)

    result = desktop_integration.install_desktop_launcher()

    assert result["ok"] is True
    desktop_path = Path(result["desktop_path"])
    icon_path = Path(result["icon_path"])
    assert desktop_path.exists()
    assert icon_path.exists()
    content = desktop_path.read_text()
    assert "Name=Ember Memory" in content
    assert 'Exec="/tmp/Ember Bin/ember-memory-controller"' in content

    status = desktop_integration.desktop_launcher_status()
    assert status["installed"] is True

    removed = desktop_integration.uninstall_desktop_launcher()
    assert removed["ok"] is True
    assert not desktop_path.exists()
    assert not icon_path.exists()


def test_windows_launcher_uses_start_menu_shortcut(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setattr(desktop_integration.platform, "system", lambda: "Windows")
    monkeypatch.setattr(desktop_integration, "_controller_command", lambda: [r"C:\Program Files\Python\python.exe", "-m", "ember_memory"])
    monkeypatch.setattr(desktop_integration, "get_icon_path", lambda: r"C:\Icons\ember-memory.png")

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))

    monkeypatch.setattr(desktop_integration.subprocess, "run", fake_run)

    result = desktop_integration.install_desktop_launcher()

    assert result["ok"] is True
    assert result["shortcut_path"].endswith(r"Microsoft/Windows/Start Menu/Programs/Ember Memory.lnk")
    command = calls[0][0]
    assert command[:4] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"]
    assert "CreateShortcut" in command[-1]
    assert "Ember Memory.lnk" in command[-1]


def test_windows_icon_path_converts_png_to_ico(monkeypatch, tmp_path):
    source = tmp_path / "ember-memory.png"
    target_home = tmp_path / "home"

    from PIL import Image

    Image.new("RGBA", (256, 256), (255, 96, 0, 255)).save(source)

    monkeypatch.setattr(desktop_integration.platform, "system", lambda: "Windows")
    monkeypatch.setattr(desktop_integration.Path, "home", lambda: target_home)
    monkeypatch.setattr(desktop_integration, "_asset_icon_path", lambda: source)

    icon_path = Path(desktop_integration.get_icon_path())

    assert icon_path.suffix == ".ico"
    assert icon_path.exists()
    with Image.open(icon_path) as icon:
        assert icon.format == "ICO"
