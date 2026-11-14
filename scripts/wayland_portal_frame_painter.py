#!/usr/bin/python3
"""Paint actual changing Wayland surfaces in the disposable pixman portal CI.

This is not a capture backend or a fake PipeWire producer. It is a normal
GTK3 client that changes its on-screen content to force compositor repaint.
"""
from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    env = os.environ
    runtime = Path(env.get("XDG_RUNTIME_DIR", ""))
    if (env.get("RICEBOWL_PORTAL_CAPTURE_CI") != "1"
            or env.get("RICEBOWL_PORTAL_STRICT_CI") != "1"
            or env.get("RICEBOWL_PORTAL_BACKEND") != "generic"
            or env.get("WLR_RENDERER") != "pixman"
            or not runtime.is_absolute()
            or runtime.is_symlink()
            or not (runtime / ".ricebowl-portal-ci").is_file()
            or env.get("GDK_BACKEND") != "wayland"):
        raise RuntimeError("Frame painter is restricted to isolated software CI")
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
