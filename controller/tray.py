#!/usr/bin/env python3
"""Ember Memory — System Tray

Quick access to heat mode controls and controller launch.
Runs independently of the controller UI.
"""

import os
import sys
import threading

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def create_icon_image():
    """Generate a simple ember-colored icon."""
    from PIL import Image, ImageDraw
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


def create_tray():
    """Create and run the system tray icon."""
    import pystray
    from pystray import MenuItem, Menu

    image = create_icon_image()
    # Try to load custom icon if available
    icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "icons", "ember-tray.png")
    if os.path.exists(icon_path):
        from PIL import Image
        image = Image.open(icon_path)

    def get_heat_mode():
        try:
            return _get_engine_state().get_config("heat_mode", "universal")
        except Exception:
            return "universal"

    def set_mode_universal(icon, item):
        try:
            _get_engine_state().set_config("heat_mode", "universal")
        except Exception:
            pass

    def set_mode_per_cli(icon, item):
        try:
            _get_engine_state().set_config("heat_mode", "per-cli")
        except Exception:
            pass

    def is_universal(item):
        return get_heat_mode() == "universal"

    def is_per_cli(item):
        return get_heat_mode() == "per-cli"

    def is_cli_active(ai_id):
        def check(item):
            try:
                return _get_engine_state().get_config(f"heat_ignore_{ai_id}", "false") != "true"
            except Exception:
                return True
        return check

    def toggle_cli(ai_id):
        def handler(icon, item):
            try:
                state = _get_engine_state()
                current = state.get_config(f"heat_ignore_{ai_id}", "false")
                state.set_config(f"heat_ignore_{ai_id}", "false" if current == "true" else "true")
            except Exception:
                pass
        return handler

    def open_controller(icon, item):
        import subprocess
        controller_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                        "setup_wizard.py")
        subprocess.Popen([sys.executable, controller_path])

    def get_stats_tooltip():
        try:
            from ember_memory.core.engine.stats import get_engine_stats
            stats = get_engine_stats(_get_engine_state())
            return (f"Ember Memory | {stats['total_memories_tracked']} tracked, "
                    f"{stats['hot_memories']} hot | "
                    f"{stats['established_connections']} connections")
        except Exception:
            return "Ember Memory"

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
        MenuItem("Quit", lambda icon, item: icon.stop()),
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
                icon.title = get_stats_tooltip()
            except Exception:
                pass
            time.sleep(30)

    tooltip_thread = threading.Thread(target=update_tooltip, daemon=True)
    tooltip_thread.start()

    icon.run()


def main():
    create_tray()


if __name__ == "__main__":
    main()
