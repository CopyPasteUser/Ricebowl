#!/usr/bin/env python3
"""Disposable fullscreen Wayland click target for the SG3 OSD pass-through check.

  sg3_click_target.py READY_FILE LOG_FILE

A single real GTK window fills the output. Every pointer press that reaches it
appends "X Y" (window = output coordinates) to LOG_FILE. READY_FILE appears once
the window is mapped, so a test can then click *through* another surface that
overlaps it (the input-transparent OSD) and assert the press arrived here.
It never reads anything but pointer coordinates and runs only inside a
disposable session; it writes only the two files it is given.
"""
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

ready, log = sys.argv[1], sys.argv[2]

window = Gtk.Window(title="SG3 click target")
box = Gtk.EventBox()
box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)


def pressed(_widget, event):
    with open(log, "a", encoding="utf-8") as stream:
        stream.write("%d %d\n" % (event.x, event.y))
    return True


box.connect("button-press-event", pressed)
window.add(box)
window.connect("destroy", Gtk.main_quit)
window.fullscreen()
window.show_all()


def announce(*_args):
    GLib.timeout_add(600, lambda: open(ready, "w", encoding="utf-8").close() or False)


window.connect("map-event", announce)
Gtk.main()
