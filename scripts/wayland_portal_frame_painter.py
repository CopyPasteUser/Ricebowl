#!/usr/bin/python3
"""Paint changing real GTK Wayland surfaces in disposable strict portal CI.

This is neither a ScreenCast backend nor a fake PipeWire producer. The same
headless compositor-damage witness is required by both the pinned generic SHM
capture lane and the optional production-wlr GLES2 capture lane.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Mapping


def allowed_private_frame_painter(env: Mapping[str, str]) -> bool:
    """Fail closed outside an owner-private strict capture runtime."""
    runtime = Path(env.get("XDG_RUNTIME_DIR", ""))
    marker = runtime / ".ricebowl-portal-ci"
    try:
        private = (runtime.is_absolute() and not runtime.is_symlink()
                   and runtime.is_dir()
                   and runtime.stat().st_uid == os.geteuid()
                   and stat.S_IMODE(runtime.stat().st_mode) == 0o700
                   and marker.is_file() and not marker.is_symlink())
    except OSError:
        return False
    return (private
            and env.get("RICEBOWL_PORTAL_CAPTURE_CI") == "1"
            and env.get("RICEBOWL_PORTAL_STRICT_CI") == "1"
            and (env.get("RICEBOWL_PORTAL_BACKEND"), env.get("WLR_RENDERER"))
                in (("generic", "pixman"), ("wlr", "gles2"))
            and env.get("GDK_BACKEND") == "wayland")


def main() -> None:
    if not allowed_private_frame_painter(os.environ):
        raise RuntimeError("Frame painter is restricted to isolated strict portal CI")
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    window = Gtk.Window(title="RiceBowl portal real-frame witness")
    window.set_default_size(480, 180)
    label = Gtk.Label(label="Wayland frame 0")
    window.add(label)
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    ticks = 0

    def repaint() -> bool:
        nonlocal ticks
        ticks += 1
        label.set_text(f"Wayland frame {ticks:06d}")
        window.queue_draw()
        return True

    GLib.timeout_add(80, repaint)
    print("PORTAL_PAINTER_OK: animated GTK Wayland surface", flush=True)
    Gtk.main()


if __name__ == "__main__":
    main()
