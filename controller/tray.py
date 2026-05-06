#!/usr/bin/env python3
"""Ember Memory — System Tray

Quick access to heat mode controls and controller launch.
Runs independently of the controller UI.
"""

import os
import signal
import shutil
import subprocess
import sys
import threading
from importlib import resources

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_controller_processes = []


def create_icon_image():
    """Load the packaged tray icon, falling back to a simple generated mark."""
    from PIL import Image, ImageDraw

    try:
        with resources.as_file(resources.files("ember_memory.assets").joinpath("ember-memory.png")) as path:
            if path.exists():
                return Image.open(path).convert("RGBA")
    except Exception:
        fallback = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "icons",
            "ember-memory.png",
        )
        if os.path.exists(fallback):
            return Image.open(fallback).convert("RGBA")

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Flame shape — simple ember orange circle with gradient effect
    draw.ellipse([8, 8, 56, 56], fill=(255, 120, 30, 255))
    draw.ellipse([16, 12, 48, 48], fill=(255, 160, 60, 255))
    draw.ellipse([22, 16, 42, 40], fill=(255, 200, 100, 200))
    return img


def _get_engine_state():
    """Lazy-load engine state."""
    from ember_memory.core.engine.state import EngineState
    from ember_memory import config
    db_path = os.path.join(config.DATA_DIR, "engine", "engine.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return EngineState(db_path=db_path)


def _cleanup_controller_processes():
    """Forget controller processes that have already exited."""
    _controller_processes[:] = [
        proc for proc in _controller_processes
        if getattr(proc, "poll", lambda: 0)() is None
    ]


def _controller_command():
    launcher = shutil.which("ember-memory-controller")
    if launcher:
        return [launcher]
    launcher = shutil.which("ember-memory")
    if launcher:
        return [launcher, "controller"]
    return [sys.executable, "-m", "ember_memory"]


def _open_controller():
    _cleanup_controller_processes()
    if _controller_processes:
        return _controller_processes[-1]

    env = {**os.environ, "EMBER_FROM_TRAY": "1"}
    proc = subprocess.Popen(
        _controller_command(),
        cwd=os.path.expanduser("~"),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _controller_processes.append(proc)
    return proc


def _terminate_controller_processes(timeout=2):
    _cleanup_controller_processes()
    processes = list(_controller_processes)
    for proc in processes:
        try:
            proc.terminate()
        except Exception:
            pass
    for proc in processes:
        try:
            proc.wait(timeout=timeout)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    _controller_processes.clear()


def _get_heat_mode():
    try:
        return _get_engine_state().get_config("heat_mode", "universal")
    except Exception:
        return "universal"


def _set_heat_mode(mode):
    try:
        _get_engine_state().set_config("heat_mode", mode)
    except Exception:
        pass


def _is_cli_active(ai_id):
    try:
        return _get_engine_state().get_config(f"heat_ignore_{ai_id}", "false") != "true"
    except Exception:
        return True


def _toggle_cli(ai_id):
    try:
        from ember_memory.core.engine.heat import HeatMap
        state = _get_engine_state()
        current = state.get_config(f"heat_ignore_{ai_id}", "false")
        HeatMap(state).set_ignored(ai_id, current != "true")
    except Exception:
        pass


def _set_cli_active(ai_id, active):
    try:
        from ember_memory.core.engine.heat import HeatMap
        state = _get_engine_state()
        HeatMap(state).set_ignored(ai_id, not active)
    except Exception:
        pass


def _get_stats_tooltip():
    try:
        from ember_memory.core.engine.stats import get_engine_stats
        stats = get_engine_stats(_get_engine_state())
        return (f"Ember Memory | {stats['total_memories_tracked']} tracked, "
                f"{stats['hot_memories']} hot | "
                f"{stats['established_connections']} connections")
    except Exception:
        return "Ember Memory"


def _icon_path():
    try:
        from ember_memory.desktop_integration import get_icon_path
        path = get_icon_path()
        if path and os.path.exists(path):
            return path
    except Exception:
        pass
    return ""


def _create_qt_tray():
    """Create a Linux tray with Qt when available."""
    from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
    from PyQt6.QtGui import QCursor, QIcon
    from PyQt6.QtWidgets import (
        QApplication,
        QButtonGroup,
        QCheckBox,
        QLabel,
        QPushButton,
        QRadioButton,
        QSystemTrayIcon,
        QVBoxLayout,
        QWidget,
    )

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)

    icon_file = _icon_path()
    icon = QIcon(icon_file) if icon_file else QIcon()
    tray = QSystemTrayIcon(icon)
    tray.setObjectName("ember-memory")
    tray.setToolTip(_get_stats_tooltip())

    panel = QWidget()
    panel.setWindowFlags(
        Qt.WindowType.Popup
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.NoDropShadowWindowHint
    )
    panel.setObjectName("emberTrayPanel")
    panel.setStyleSheet("""
        QWidget#emberTrayPanel {
            background: #090806;
            border: 1px solid #3a2415;
            border-radius: 8px;
        }
        QLabel.section {
            color: #b88755;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0;
            padding-top: 4px;
        }
        QLabel.status {
            color: #ffb56b;
            font-size: 11px;
            min-height: 16px;
        }
        QRadioButton, QCheckBox {
            color: #f0d9bd;
            spacing: 8px;
            min-height: 22px;
        }
        QRadioButton::indicator, QCheckBox::indicator {
            width: 14px;
            height: 14px;
        }
        QPushButton {
            background: #17100b;
            color: #ffd9b0;
            border: 1px solid #3a2415;
            border-radius: 5px;
            min-height: 26px;
            padding: 3px 10px;
        }
        QPushButton:hover {
            background: #24170f;
            border-color: #ff7820;
        }
    """)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(5)

    def add_label(text):
        label = QLabel(text)
        label.setProperty("class", "section")
        layout.addWidget(label)

    def add_radio(text):
        radio = QRadioButton(text)
        layout.addWidget(radio)
        return radio

    def add_checkbox(text):
        checkbox = QCheckBox(text)
        layout.addWidget(checkbox)
        return checkbox

    add_label("Heat Mode")
    universal_radio = add_radio("Universal")
    per_cli_radio = add_radio("Per-CLI")
    heat_group = QButtonGroup(panel)
    heat_group.setExclusive(True)
    heat_group.addButton(universal_radio)
    heat_group.addButton(per_cli_radio)

    add_label("AI Lanes")
    cli_checkboxes = {}
    for ai_id, label in (
        ("claude", "Claude Code"),
        ("gemini", "Gemini CLI"),
        ("codex", "Codex"),
    ):
        cli_checkboxes[ai_id] = add_checkbox(label)

    status_label = QLabel("")
    status_label.setProperty("class", "status")
    status_label.hide()

    open_button = QPushButton("Open Controller")
    quit_button = QPushButton("Quit")
    layout.addSpacing(5)
    layout.addWidget(status_label)
    layout.addWidget(open_button)
    layout.addWidget(quit_button)

    class TrayBridge(QObject):
        action_done = pyqtSignal()

    bridge = TrayBridge(panel)

    def set_quick_controls_enabled(enabled):
        universal_radio.setEnabled(enabled)
        per_cli_radio.setEnabled(enabled)
        for checkbox in cli_checkboxes.values():
            checkbox.setEnabled(enabled)

    def refresh_panel(update_tooltip=True):
        mode = _get_heat_mode()
        universal_radio.blockSignals(True)
        per_cli_radio.blockSignals(True)
        universal_radio.setChecked(mode == "universal")
        per_cli_radio.setChecked(mode == "per_cli")
        universal_radio.blockSignals(False)
        per_cli_radio.blockSignals(False)
        for ai_id, checkbox in cli_checkboxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(_is_cli_active(ai_id))
            checkbox.blockSignals(False)
        if update_tooltip:
            tray.setToolTip(_get_stats_tooltip())

    def finish_quick_action():
        status_label.hide()
        status_label.setText("")
        set_quick_controls_enabled(True)
        refresh_panel(update_tooltip=False)

    def run_quick_action(callback):
        status_label.setText("Updating...")
        status_label.show()
        set_quick_controls_enabled(False)

        def worker():
            try:
                callback()
            finally:
                bridge.action_done.emit()

        threading.Thread(target=worker, daemon=True).start()

    def quit_tray():
        _terminate_controller_processes()
        app.quit()

    def show_panel():
        refresh_panel()
        panel.adjustSize()
        pos = QCursor.pos()
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            x = min(pos.x(), available.right() - panel.width())
            y = min(pos.y(), available.bottom() - panel.height())
            panel.move(max(available.left(), x), max(available.top(), y))
        else:
            panel.move(pos)
        panel.show()
        panel.raise_()
        panel.activateWindow()

    bridge.action_done.connect(finish_quick_action)
    universal_radio.toggled.connect(
        lambda checked: checked and run_quick_action(lambda: _set_heat_mode("universal"))
    )
    per_cli_radio.toggled.connect(
        lambda checked: checked and run_quick_action(lambda: _set_heat_mode("per_cli"))
    )
    for ai_id, checkbox in cli_checkboxes.items():
        checkbox.toggled.connect(
            lambda checked=False, value=ai_id: run_quick_action(
                lambda: _set_cli_active(value, checked)
            )
        )
    open_button.clicked.connect(_open_controller)
    quit_button.clicked.connect(quit_tray)
    app.aboutToQuit.connect(_terminate_controller_processes)

    def on_activated(reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            _open_controller()
        elif reason == QSystemTrayIcon.ActivationReason.Context:
            show_panel()

    tray.activated.connect(on_activated)
    refresh_panel()
    tray.show()

    timer = QTimer()
    timer.timeout.connect(refresh_panel)
    timer.start(30000)

    signal.signal(signal.SIGINT, lambda *_: quit_tray())
    signal.signal(signal.SIGTERM, lambda *_: quit_tray())

    app.exec()
    tray.hide()
    return False


def create_tray():
    """Create and run the system tray icon."""
    if sys.platform.startswith("linux"):
        try:
            return _create_qt_tray()
        except Exception as e:
            print(f"Qt tray unavailable, falling back to pystray: {e}")

    try:
        import pystray
        from pystray import MenuItem, Menu
    except ImportError:
        print("Error: pystray not installed. Run: pip install pystray")
        sys.exit(1)
    except ValueError as e:
        # Linux: missing system tray libraries
        if "AppIndicator" in str(e) or "Ayatana" in str(e):
            print("Error: System tray libraries not available.")
            print("")
            print("Linux users need to install system packages:")
            print("  Ubuntu/Debian:")
            print("    sudo apt install libappindicator3-1 gir1.2-appindicator3-0.1")
            print("    or:")
            print("    sudo apt install libayatana-appindicator3-1 gir1.2-ayatanaappindicator3-0.1")
            print("  Fedora:")
            print("    sudo dnf install libappindicator-gtk3 appindicator-sharp")
            print("")
            print("See README.md for details.")
            sys.exit(1)
        else:
            raise

    image = create_icon_image()
    # Try to load custom icon if available
    icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "icons", "ember-tray.png")
    if os.path.exists(icon_path):
        from PIL import Image
        image = Image.open(icon_path)

    def set_mode_universal(icon, item):
        _set_heat_mode("universal")

    def set_mode_per_cli(icon, item):
        _set_heat_mode("per_cli")

    def is_universal(item):
        return _get_heat_mode() == "universal"

    def is_per_cli(item):
        return _get_heat_mode() == "per_cli"

    def is_cli_active(ai_id):
        def check(item):
            return _is_cli_active(ai_id)
        return check

    def toggle_cli(ai_id):
        def handler(icon, item):
            _toggle_cli(ai_id)
        return handler

    def open_controller(icon, item):
        _open_controller()

    def quit_app(icon, item):
        # os._exit to avoid GTK callback deadlock from pystray menu handler
        _terminate_controller_processes()
        os._exit(0)

    menu = Menu(
        MenuItem("Heat Mode", Menu(
            MenuItem("Universal", set_mode_universal, checked=is_universal),
            MenuItem("Per-CLI", set_mode_per_cli, checked=is_per_cli),
        )),
        Menu.SEPARATOR,
        MenuItem("Claude Code", toggle_cli("claude"), checked=is_cli_active("claude")),
        MenuItem("Gemini CLI", toggle_cli("gemini"), checked=is_cli_active("gemini")),
        MenuItem("Codex", toggle_cli("codex"), checked=is_cli_active("codex")),
        Menu.SEPARATOR,
        MenuItem("Open Controller", open_controller),
        MenuItem("Quit", quit_app),
    )

    icon = pystray.Icon(
        "ember-memory",
        image,
        "Ember Memory",
        menu,
    )

    # Update tooltip periodically
    def update_tooltip():
        import time
        while icon.visible:
            try:
                icon.title = _get_stats_tooltip()
            except Exception:
                pass
            time.sleep(30)

    tooltip_thread = threading.Thread(target=update_tooltip, daemon=True)
    tooltip_thread.start()

    icon.run()
    return False


def main():
    from ember_memory.single_instance import acquire_instance_lock

    lock = acquire_instance_lock("tray")
    if lock is None:
        print("Ember Memory tray is already running.")
        return
    try:
        create_tray()
    finally:
        lock.close()


if __name__ == "__main__":
    main()
