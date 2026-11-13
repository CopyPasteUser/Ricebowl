#!/usr/bin/env python3
"""Capture genuine Luna GTK clients through grim in an isolated *labwc* session.

This script does not start labwc: the companion shell harness does. These are
compositor pixels, not Gdk.pixbuf_get_from_window() or synthetic mocks.
No hardware settings are applied and no rice/selection is installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from macrice.de.settings import RiceSpiceWindow, _gtk_modules
from macrice import luna_help

EXPECTED = ("home", "category", "classic", "input", "taskbar", "search",
            "help", "properties", "confirmation")


def main() -> int:
    start = time.perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    destination = args.output_dir.resolve()
    if not destination.is_absolute() or not destination.is_dir() or any(destination.iterdir()):
        parser.error("Use an existing, empty absolute capture directory")
    if not os.environ.get("WAYLAND_DISPLAY") or os.environ.get("GDK_BACKEND") != "wayland":
        parser.error("Requires the isolated labwc Wayland/GTK client environment")
    Gtk, Gdk, GLib = _gtk_modules()
    if not Gtk.init_check([])[0]:
        parser.error("Cannot connect to the actual Wayland GTK display")

    panel = RiceSpiceWindow(Gtk, Gdk, GLib, page="home", luna=True)
    panel.window.resize(840, 620)
    panel.window.present()
    pngs = []
    dialogs = []
    failures = []

    class Shell:
        bar = panel.window
        actions = None
        _luna_help_dialog = None
        _luna_system_dialog = None

        def _hide_menu(self):
            return None

        def _desktop_rect(self):
            return SimpleNamespace(x=0, y=0, width=1024, height=768)

        def luna_control_show_category(self, _name):
            raise AssertionError("Help capture must not launch a setting")

        def _toggle_actions(self):
            raise AssertionError("Help capture must not open Control Panel")

    shell = Shell()

    def screenshot(name: str):
        target = destination / f"luna-labwc-{name}.png"
        if target.exists():
            raise RuntimeError("Refusing to overwrite a native screenshot")
        subprocess.run(["grim", str(target)], check=True, timeout=8,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if target.stat().st_size < 14000:
            raise RuntimeError(f"Empty or unrendered compositor frame: {name}")
        pngs.append(target)

    def open_help():
        help_dialog = luna_help.show_help(shell, Gtk)
        dialogs.append(help_dialog)

    def open_properties():
        properties = luna_help.show_system(shell, Gtk)
        dialogs.append(properties)

    def open_confirmation():
        if shell._luna_system_dialog is not None:
            shell._luna_system_dialog.hide()
        panel.window.show_all()
        modal = Gtk.MessageDialog(
            transient_for=panel.window, modal=False,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Apply these settings?")
        modal.format_secondary_text(
            "This is a visual-only confirmation example. No settings will be changed.")
        modal.get_style_context().add_class("luna-owned-dialog")
        modal.show_all()
        dialogs.append(modal)

    routes = (
        ("home", lambda: panel.show_home()),
        ("category", lambda: panel.show_category("sound")),
        ("classic", lambda: (setattr(panel, "luna_view", "classic"), panel.show_home())),
        ("input", lambda: panel.show_page("input")),
        ("taskbar", lambda: panel.show_page("taskbar")),
        ("search", lambda: panel.search_entry.set_text("speaker")),
        ("help", open_help),
        ("properties", open_properties),
        ("confirmation", open_confirmation),
    )

    def advance(index: int):
        try:
            if index >= len(routes):
                for item in reversed(dialogs):
                    item.destroy()
                panel.window.destroy()
                return False
            name, visit = routes[index]
            visit()
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            # An actual compositor frame is acquired only after the mapped
            # surface has had time to be configured and repainted.
            GLib.timeout_add(310, save, index, name)
        except Exception as exc:
            failures.append(f"Route {index}: {exc}")
            for item in reversed(dialogs):
                item.destroy()
            panel.window.destroy()
        return False

    def save(index: int, name: str):
        try:
            # Help and Properties are real GTK dialogs; their parent settings
            # window may be hidden, but the dialogs must remain visible.
            if name in ("help", "properties", "confirmation"):
                dialog = dialogs[-1]
                if not dialog.get_mapped():
                    raise RuntimeError("Expected system dialog did not map on labwc")
            else:
                if not panel.window.get_mapped():
                    raise RuntimeError("Control Panel did not map on labwc")
                if panel.page != ("category" if name == "category" else
                                  "search" if name == "search" else
                                  "home" if name in ("home", "classic") else name):
                    raise RuntimeError("GTK view did not navigate to " + name)
            screenshot(name)
            GLib.timeout_add(90, advance, index + 1)
        except Exception as exc:
            failures.append(f"Capture {name}: {exc}")
            for item in reversed(dialogs):
                item.destroy()
            panel.window.destroy()
        return False

    GLib.timeout_add(550, advance, 0)
    Gtk.main()
    if failures:
        raise RuntimeError("; ".join(failures))
    if [p.name for p in pngs] != [f"luna-labwc-{name}.png" for name in EXPECTED]:
        raise RuntimeError("Missing real compositor captures")
    from PIL import Image
    hashes = set()
    for path in pngs:
        with Image.open(path) as im:
            im.load()
            if im.size != (1024, 768):
                raise RuntimeError(f"Unexpected headless output size: {im.size}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in hashes:
            raise RuntimeError(f"Duplicate compositor frame: {path.name}")
        hashes.add(digest)
    receipt = {
        "source": "real grim frames, native GTK Wayland client on headless labwc",
        "output": [1024, 768],
        "frames": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in pngs},
        "process_start_to_completion_ms": round((time.perf_counter() - start) * 1000, 2),
        "session": "isolated headless CI, NOT physical Mint hardware",
        "physical_input_accessibility": "not tested",
    }
    (destination / "luna-labwc-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
