"""Ember Memory v2.0 — entry point for all commands."""

import os
import subprocess
import sys

EMBER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def launch_app_detached():
    """Launch the controller as a detached app process and return immediately."""
    env = {**os.environ, "EMBER_APP_LAUNCHER": "1"}
    command = [sys.executable, "-m", "ember_memory", "controller"]
    popen_kwargs = {
        "cwd": os.path.expanduser("~"),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    return subprocess.Popen(command, **popen_kwargs)


def launch_controller():
    """Launch the desktop controller."""
    from ember_memory.controller_app import main as controller_main

    controller_main()


def launch_tray():
    """Launch the system tray."""
    sys.path.insert(0, EMBER_ROOT)
    from controller.tray import main as tray_main

    tray_main()


def print_desktop_result(action):
    from ember_memory.desktop_integration import (
        desktop_launcher_status,
        format_result,
        install_desktop_launcher,
        uninstall_desktop_launcher,
    )

    actions = {
        "install-desktop": install_desktop_launcher,
        "uninstall-desktop": uninstall_desktop_launcher,
        "desktop-status": desktop_launcher_status,
    }
    print(format_result(actions[action]()))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "launch"

    if cmd in {"launch", "app"}:
        launch_app_detached()

    elif cmd == "controller" or cmd == "ui":
        launch_controller()

    elif cmd == "tray":
        launch_tray()

    elif cmd == "setup":
        launch_controller()

    elif cmd == "monitor":
        sys.argv = sys.argv[1:]
        from ember_memory.monitor import main as monitor_main
        monitor_main()

    elif cmd in {"install-desktop", "uninstall-desktop", "desktop-status"}:
        print_desktop_result(cmd)

    else:
        print("Ember Memory v2.0")
        print()
        print("Commands:")
        print("  python -m ember_memory               Launch the app and return immediately")
        print("  python -m ember_memory controller     Launch the controller in the foreground")
        print("  python -m ember_memory install-desktop Create app launcher / Start Menu shortcut")
        print("  python -m ember_memory uninstall-desktop Remove app launcher / Start Menu shortcut")
        print("  python -m ember_memory desktop-status Check desktop launcher status")
        print("  python -m ember_memory tray           Launch the system tray")
        print("  python -m ember_memory setup          Launch the controller in the foreground")
        print("  python -m ember_memory monitor        Live activity monitor")
        print()
        print("Quick start:")
        print("  python -m ember_memory                Open the app")


if __name__ == "__main__":
    main()
