"""Install/remove native desktop launchers for Ember Memory."""

from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path


APP_ID = "com.kindledflamestudios.EmberMemory"
APP_NAME = "Ember Memory"
DESKTOP_FILENAME = f"{APP_ID}.desktop"


def _controller_command() -> list[str]:
    launcher = shutil.which("ember-memory-controller")
    if launcher:
        return [launcher]
    launcher = shutil.which("ember-memory")
    if launcher:
        return [launcher, "controller"]
    return [sys.executable, "-m", "ember_memory"]


def _quote_desktop_arg(value: str) -> str:
    if not value:
        return '""'
    if any(ch.isspace() or ch in '"\\' for ch in value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _desktop_exec_line(command: list[str]) -> str:
    return " ".join(_quote_desktop_arg(part) for part in command)


def _asset_icon_path() -> Path | None:
    try:
        with resources.as_file(resources.files("ember_memory.assets").joinpath("ember-memory.png")) as path:
            return Path(path)
    except Exception:
        fallback = Path(__file__).resolve().parents[1] / "icons" / "ember-memory.png"
        return fallback if fallback.exists() else None


def _windows_icon_path() -> Path | None:
    source = _asset_icon_path()
    if not source or not source.exists():
        return None

    target = Path.home() / ".ember-memory" / "ember-memory.ico"
    try:
        if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
            return target

        target.parent.mkdir(parents=True, exist_ok=True)
        from PIL import Image

        with Image.open(source) as img:
            img.save(
                target,
                format="ICO",
                sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)],
            )
        return target
    except Exception:
        return None


def get_icon_path() -> str:
    if platform.system() == "Windows":
        path = _windows_icon_path()
        return str(path) if path else ""
    path = _asset_icon_path()
    return str(path) if path else ""


def _linux_paths() -> tuple[Path, Path]:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    desktop_path = data_home / "applications" / DESKTOP_FILENAME
    icon_path = data_home / "icons" / "hicolor" / "256x256" / "apps" / "ember-memory.png"
    return desktop_path, icon_path


def install_linux_launcher() -> dict:
    desktop_path, icon_path = _linux_paths()
    source_icon = _asset_icon_path()

    desktop_path.parent.mkdir(parents=True, exist_ok=True)
    icon_name = "ember-memory"
    if source_icon and source_icon.exists():
        icon_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_icon, icon_path)

    content = "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            f"Name={APP_NAME}",
            "Comment=Local-first memory controller for AI CLIs",
            f"Exec={_desktop_exec_line(_controller_command())}",
            f"Icon={icon_name}",
            "Terminal=false",
            "Categories=Development;Utility;",
            "StartupNotify=true",
            f"StartupWMClass={APP_NAME}",
            "",
        ]
    )
    desktop_path.write_text(content)
    desktop_path.chmod(0o755)

    if shutil.which("update-desktop-database"):
        subprocess.run(
            ["update-desktop-database", str(desktop_path.parent)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    return {
        "ok": True,
        "platform": "linux",
        "desktop_path": str(desktop_path),
        "icon_path": str(icon_path) if icon_path.exists() else "",
        "msg": f"Installed {APP_NAME} launcher",
    }


def uninstall_linux_launcher() -> dict:
    desktop_path, icon_path = _linux_paths()
    removed = []
    for path in (desktop_path, icon_path):
        if path.exists():
            path.unlink()
            removed.append(str(path))
    if shutil.which("update-desktop-database") and desktop_path.parent.exists():
        subprocess.run(
            ["update-desktop-database", str(desktop_path.parent)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    return {"ok": True, "platform": "linux", "removed": removed, "msg": "Removed desktop launcher"}


def _windows_shortcut_path() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def install_windows_launcher() -> dict:
    shortcut = _windows_shortcut_path()
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    command = _controller_command()
    target = command[0]
    args = subprocess.list2cmdline(command[1:])
    icon = get_icon_path()

    script_lines = [
        "$shell = New-Object -ComObject WScript.Shell",
        f"$shortcut = $shell.CreateShortcut({_powershell_quote(str(shortcut))})",
        f"$shortcut.TargetPath = {_powershell_quote(target)}",
        f"$shortcut.Arguments = {_powershell_quote(args)}",
        f"$shortcut.WorkingDirectory = {_powershell_quote(str(Path.home()))}",
        f"$shortcut.Description = {_powershell_quote(APP_NAME)}",
    ]
    if icon:
        script_lines.append(f"$shortcut.IconLocation = {_powershell_quote(icon)}")
    script_lines.append("$shortcut.Save()")

    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "; ".join(script_lines)],
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        "ok": True,
        "platform": "windows",
        "shortcut_path": str(shortcut),
        "msg": f"Installed {APP_NAME} Start Menu shortcut",
    }


def uninstall_windows_launcher() -> dict:
    shortcut = _windows_shortcut_path()
    removed = []
    if shortcut.exists():
        shortcut.unlink()
        removed.append(str(shortcut))
    return {"ok": True, "platform": "windows", "removed": removed, "msg": "Removed Start Menu shortcut"}


def install_desktop_launcher() -> dict:
    system = platform.system()
    if system == "Linux":
        return install_linux_launcher()
    if system == "Windows":
        return install_windows_launcher()
    return {"ok": False, "platform": system.lower(), "msg": f"Desktop launcher install is not supported on {system}"}


def uninstall_desktop_launcher() -> dict:
    system = platform.system()
    if system == "Linux":
        return uninstall_linux_launcher()
    if system == "Windows":
        return uninstall_windows_launcher()
    return {"ok": False, "platform": system.lower(), "msg": f"Desktop launcher uninstall is not supported on {system}"}


def desktop_launcher_status() -> dict:
    system = platform.system()
    if system == "Linux":
        desktop_path, icon_path = _linux_paths()
        return {
            "ok": True,
            "platform": "linux",
            "installed": desktop_path.exists(),
            "desktop_path": str(desktop_path),
            "icon_path": str(icon_path),
        }
    if system == "Windows":
        shortcut = _windows_shortcut_path()
        return {
            "ok": True,
            "platform": "windows",
            "installed": shortcut.exists(),
            "shortcut_path": str(shortcut),
        }
    return {"ok": True, "platform": system.lower(), "installed": False}


def format_result(result: dict) -> str:
    return json.dumps(result, indent=2)
