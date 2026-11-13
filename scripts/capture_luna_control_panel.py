#!/usr/bin/env python3
"""Capture the *actual* Luna GTK Control Panel in an isolated Xvfb session.

No synthetic mockups or backend actions: overview and taskbar navigation only.
These X11 GTK client captures are visual QA, not native-Wayland proof.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Standalone capture invoked as scripts/capture_*.py from repository root or CI.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from macrice.de.settings import RiceSpiceWindow, _gtk_modules


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    Gtk, Gdk, GLib = _gtk_modules()
    if not Gtk.init_check([])[0]:
        parser.error("This capture requires a graphical GTK display (use xvfb-run).")

    panel = RiceSpiceWindow(Gtk, Gdk, GLib, page="home", luna=True)
    panel.window.resize(960, 660)
    panel.window.set_position(Gtk.WindowPosition.CENTER)
    panel.window.present()

    def capture(filename: str) -> None:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        widget = panel.window.get_window()
        if widget is None:
            raise RuntimeError("Luna GTK window is not mapped")
        width = widget.get_width()
        height = widget.get_height()
        if width < 700 or height < 470:
            raise RuntimeError(f"Luna screenshot clipped: {width}x{height}")
        pixels = Gdk.pixbuf_get_from_window(widget, 0, 0, width, height)
        if pixels is None:
            raise RuntimeError("Could not capture the real GTK framebuffer")
        destination = out / filename
        if destination.exists():
            raise RuntimeError(f"Refusing to overwrite {destination}")
        pixels.savev(str(destination), "png", [], [])
        print(f"Captured GTK client: {destination} ({width}x{height})")

    def capture_overview():
        try:
            capture("luna-control-panel-home.png")
            panel.show_page("taskbar")  # No hardware mutation or blocking scan.
            GLib.timeout_add(380, capture_taskbar)
        except Exception as error:
            print(f"Control Panel capture failed: {error}")
            panel.window.destroy()
            raise
        return False

    def capture_taskbar():
        try:
            capture("luna-control-panel-taskbar.png")
        finally:
            panel.window.destroy()
        return False

    GLib.timeout_add(450, capture_overview)
    Gtk.main()
    expected = (out / "luna-control-panel-home.png",
                out / "luna-control-panel-taskbar.png")
    if not all(file.is_file() and file.stat().st_size > 12000 for file in expected):
        raise RuntimeError("One or more Control Panel captures are missing or blank")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
