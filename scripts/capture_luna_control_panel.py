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

    # Every frame below is a mapped, genuine GTK client surface captured
    # after the corresponding button/route transition. Xvfb is NOT labwc.
    frames = (
        ("home", lambda: panel.show_home()),
        ("category", lambda: panel.show_category("sound")),
        ("classic", lambda: (setattr(panel, "luna_view", "classic"), panel.show_home())),
        ("input", lambda: panel.show_page("input")),
        ("taskbar", lambda: panel.show_page("taskbar")),
        ("search", lambda: panel.search_entry.set_text("sound")),
    )
    paths = []

    def advance(index: int):
        try:
            if index >= len(frames):
                panel.window.destroy()
                return False
            name, navigate = frames[index]
            navigate()
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            if name == "category" and panel.page != "category":
                raise RuntimeError("Category view did not open")
            if name == "search" and panel.page != "search":
                raise RuntimeError("Search view did not open")
            if name == "classic" and panel.luna_view != "classic":
                raise RuntimeError("Classic View did not open")
            filename = f"luna-control-panel-{name}.png"
            # One extra GTK idle iteration lets CSS and FlowBox allocation
            # settle before saving the real mapped client.
            def save_and_next():
                try:
                    capture(filename)
                    paths.append(out / filename)
                    GLib.timeout_add(100, advance, index + 1)
                except Exception:
                    panel.window.destroy()
                    raise
                return False
            GLib.timeout_add(180, save_and_next)
        except Exception:
            panel.window.destroy()
            raise
        return False

    GLib.timeout_add(500, advance, 0)
    Gtk.main()
    if len(paths) != len(frames) or not all(
            file.is_file() and file.stat().st_size > 12000 for file in paths):
        raise RuntimeError("One or more real Control Panel captures are missing or blank")

    # Lightweight CI-only observations, not a promise of actual laptop PSS
    # or compositor idle CPU. Read only this process' /proc information.
    import json
    import os
    import time
    metrics = {"environment": "GTK client under Xvfb, not native labwc",
               "capture_count": len(paths),
               "capture_names": [path.name for path in paths],
               "screenshot_bytes": {path.name: path.stat().st_size for path in paths},
               "process_count_measured": 1,
               "cpu_process_seconds_at_end": time.process_time()}
    try:
        status = Path(f"/proc/{os.getpid()}/status").read_text()
        metrics["rss_kib_at_end"] = int(next(
            line.split()[1] for line in status.splitlines()
            if line.startswith("VmRSS:")))
        rollup = Path(f"/proc/{os.getpid()}/smaps_rollup").read_text()
        metrics["pss_kib_at_end"] = int(next(
            line.split()[1] for line in rollup.splitlines()
            if line.startswith("Pss:")))
    except (OSError, ValueError, StopIteration):
        metrics["memory_measurement"] = "unavailable"
    (out / "luna-control-panel-capture-metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
