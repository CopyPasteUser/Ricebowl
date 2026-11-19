"""X11 Aqua tray focus lifecycle: pre-activation WM events are not dismissal.

Pure GTK protocol doubles exercise the real registered signal callbacks without
requiring a user's X display, compositor, or notification service.
"""

from __future__ import annotations

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from macrice import frutiger_tray_window as tray


class FakeWindow:
    def __init__(self, *args, **kwargs):
        self.handlers = {}
        self.visible = False
        self.active = False
        self.hide_count = 0
        self.style_classes = []

    def __getattr__(self, name):
        if name.startswith("set_"):
            return lambda *args, **kwargs: None
        raise AttributeError(name)

    def connect(self, signal, callback):
        self.handlers[signal] = callback

    def get_style_context(self):
        return SimpleNamespace(add_class=self.style_classes.append)

    def show_all(self):
        self.visible = True

    def present(self):
        pass  # The real window manager confirms focus asynchronously.

    def hide(self):
        self.visible = False
        self.hide_count += 1

    def get_visible(self):
        return self.visible

    def is_active(self):
        return self.active


class AquaTrayFocusTests(unittest.TestCase):
    def setUp(self):
        self.original_class = tray._TRAY_CLASS
        tray._TRAY_CLASS = None
        self.addCleanup(setattr, tray, "_TRAY_CLASS", self.original_class)
        self.timers = []
        glib = SimpleNamespace(
            timeout_add=lambda delay, callback, *args: self.timers.append(
                (delay, callback, args)) or len(self.timers),
            idle_add=lambda callback, *args: 1,
        )
        gdk = SimpleNamespace(
            WindowTypeHint=SimpleNamespace(UTILITY=1),
            KEY_Escape=65307,
        )
        repository = ModuleType("gi.repository")
        repository.Gdk = gdk
        repository.GLib = glib
        gi = ModuleType("gi")
        gi.repository = repository
        patcher = patch.dict(sys.modules, {"gi": gi, "gi.repository": repository})
        patcher.start()
        self.addCleanup(patcher.stop)
        gtk = SimpleNamespace(Window=FakeWindow, WindowType=SimpleNamespace(TOPLEVEL=1))
        anchor = SimpleNamespace(get_toplevel=lambda: None, get_realized=lambda: False)
        self.window = tray.create_tray_window(anchor, gtk)

    def event(self, name):
        return self.window.handlers[name](self.window, None)

    def run_timers(self):
        pending, self.timers = self.timers, []
        for _delay, callback, args in pending:
            callback(*args)

    def test_early_focus_out_before_wm_activation_does_not_dismiss(self):
        self.window.popup()
        self.assertTrue(self.window.get_visible())
        self.assertFalse(self.event("focus-out-event"))
        self.assertEqual(self.timers, [])
        self.assertEqual(self.window.hide_count, 0)

    def test_real_focus_loss_still_closes_visible_flyout(self):
        self.window.popup()
        self.window.active = True
        self.assertFalse(self.event("focus-in-event"))
        self.window.active = False
        self.event("focus-out-event")
        self.assertEqual(len(self.timers), 1)
        self.assertEqual(self.timers[0][0], 180)
        self.run_timers()
        self.assertFalse(self.window.get_visible())
        self.assertEqual(self.window.hide_count, 1)

    def test_already_active_window_is_recognized_on_popup(self):
        # Existing callers call show_all() before popup(); no extra focus-in
        # event is guaranteed for an already active X11 utility window.
        self.window.show_all()
        self.window.active = True
        self.window.popup()
        self.window.active = False
        self.event("focus-out-event")
        self.run_timers()
        self.assertFalse(self.window.get_visible())

    def test_old_focus_out_cannot_hide_new_presentation(self):
        self.window.popup()
        self.window.active = True
        self.event("focus-in-event")
        self.window.active = False
        self.event("focus-out-event")
        self.window.popdown()
        self.window.popup()
        self.run_timers()
        self.assertTrue(self.window.get_visible())
        self.assertEqual(self.window.hide_count, 1)

    def test_escape_always_dismisses_without_focus_lease(self):
        self.window.popup()
        result = self.window.handlers["key-press-event"](
            self.window, SimpleNamespace(keyval=65307))
        self.assertTrue(result)
        self.assertFalse(self.window.get_visible())
        self.assertFalse(self.window._focus_confirmed)


if __name__ == "__main__":
    unittest.main()
