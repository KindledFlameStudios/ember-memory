"""Ember Memory v2.0 — entry point for all commands."""

import os
import sys

EMBER_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "controller"

    if cmd == "controller" or cmd == "ui":
        # Launch the desktop controller
        sys.path.insert(0, EMBER_ROOT)
        from setup_wizard import main as controller_main
        controller_main()

    elif cmd == "tray":
        # Launch the system tray
        sys.path.insert(0, EMBER_ROOT)
        from controller.tray import main as tray_main
        tray_main()

    elif cmd == "setup":
        # Launch controller in setup mode (same app, future: auto-open setup tab)
        sys.path.insert(0, EMBER_ROOT)
        from setup_wizard import main as setup_main
        setup_main()

    elif cmd == "monitor":
        sys.argv = sys.argv[1:]
        from ember_memory.monitor import main as monitor_main
        monitor_main()

    else:
        print("Ember Memory v2.0")
        print()
        print("Commands:")
        print("  python -m ember_memory               Launch the controller (default)")
        print("  python -m ember_memory controller     Launch the desktop controller")
        print("  python -m ember_memory tray           Launch the system tray")
        print("  python -m ember_memory setup          Run the setup wizard")
        print("  python -m ember_memory monitor        Live activity monitor")
        print()
        print("Quick start:")
        print("  python -m ember_memory setup          First-time setup")
        print("  python -m ember_memory                Open the controller")


if __name__ == "__main__":
    main()
