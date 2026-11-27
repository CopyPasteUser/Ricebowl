"""RiceSpice status line: fixed strip, never a stale "working" claim (SG2 WP2.4).

Both defects were found by the real-labwc GUI pass (scripts/sg2_settings_gui_driver.py):
* the status line was the last child of the SCROLLED page, so on the long Network
  page a denial of a control at the top was below the fold and invisible;
* a read whose page states its own outcome in the body (provider unavailable) left
  "Working with system services…" on screen forever.
"""
import threading
import unittest

from macrice.de import settings
from macrice.de import settings_backend as backend
from tests.test_de_settings_gui_controls import _GuiCase


class StatusStripTests(_GuiCase):
    def test_status_is_outside_the_scrolled_page_and_hidden_when_empty(self):
        self.window.show_page("network")
        status = self.window.status
        self.assertFalse(status.is_ancestor(self.window.content),
                         "status must not scroll with the page content")
        scrolled = self.window.content.get_ancestor(self.Gtk.ScrolledWindow)
        self.assertIsNotNone(scrolled)
        self.assertFalse(status.is_ancestor(scrolled),
                         "status must not live inside the scrolled window")
        self.assertIs(status.get_parent(), scrolled.get_parent(),
                      "status is the fixed strip beside the scrolled page")
        self.window._state("")
        self.assertFalse(status.get_visible())
        self.window._state("Permission denied")
        self.assertTrue(status.get_visible())
        self.assertEqual(status.get_text(), "Permission denied")

    def test_status_survives_page_navigation_as_one_widget_and_is_cleared(self):
        self.window.show_page("network")
        widget = self.window.status
        self.window._state("old result")
        self.window.show_page("bluetooth")
        self.assertIs(self.window.status, widget)
        self.assertNotEqual(self.window.status.get_text(), "old result")

    def test_unavailable_provider_does_not_leave_working_text_behind(self):
        self.fake.wifi_error = backend.SettingsError("NetworkManager is not running")
        self.window.show_page("network")
        self.assertTrue(self.pump(lambda: any(
            "Wi-Fi radio/scan unavailable" in text for text in self.texts())), self.texts())
        self.settle()
        self.assertNotEqual(self.status(), settings.WORKING_TEXT)
        self.assertEqual(self.status(), "")
        self.assertFalse(self.window.status.get_visible())

    def test_working_text_shows_while_in_flight_and_is_replaced_by_the_outcome(self):
        self.open_page("network", "Disable Wi-Fi")
        self.fake.gate = threading.Event()
        self.click("Disable Wi-Fi")
        self.assertEqual(self.status(), settings.WORKING_TEXT)
        self.assertTrue(self.window.status.get_visible())
        self.fake.gate.set()
        self.assertTrue(self.pump(lambda: self.status() == "Wi-Fi radio: disabled"),
                        self.status())

    def test_a_follow_up_request_keeps_its_own_working_text(self):
        # done() may start the next request (a page refresh): the cleanup must not
        # wipe that request's "working" status while it is still running.
        self.open_page("network", "Disable Wi-Fi")
        gate = threading.Event()
        original = self.fake.wifi_snapshot
        calls = []

        def slow_snapshot(rescan=False):
            calls.append(1)
            gate.wait(5)
            return original(rescan)

        try:
            from unittest import mock
            with mock.patch.object(backend, "wifi_snapshot", slow_snapshot):
                self.click("Disable Wi-Fi")
                self.assertTrue(self.pump(lambda: len(calls) == 1))
                self.assertTrue(self.window.busy)
                self.assertEqual(self.status(), settings.WORKING_TEXT)
                gate.set()
                self.assertTrue(self.pump(lambda: self.status() == "Wi-Fi radio: disabled"),
                                self.status())
        finally:
            gate.set()


if __name__ == "__main__":
    unittest.main()
