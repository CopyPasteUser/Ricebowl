"""Headless GTK tests that DRIVE RiceSpice's real settings controls (SG2 gap 2/6/8).

Real Gtk widgets and the real `RiceSpiceWindow._background` worker/idle path are
used; only the settings backend boundary is replaced by a fake adapter. Each
control is clicked (`clicked`) and the visible label text, the re-rendered
readback and widget state are asserted for: verified success, typed
`SettingsDenied`, generic error, busy (second click refused, no second backend
call) and an indeterminate/stale outcome (shown once, never replayed).
"""

import threading
import time
import unittest
from contextlib import ExitStack
from unittest import mock

from macrice import authorization
from macrice.de import settings
from macrice.de import settings_backend as backend
from macrice.de.wayland_displays import Output

UNKNOWN = "Automatic time may have changed; outcome unknown; refresh before retrying"


class FakeAdapters:
    """Fake system services at the settings_backend boundary."""

    def __init__(self):
        self.wifi = True
        self.networks = []
        self.wifi_error = None
        self.ntp = True
        self.clock_ntp_value = None
        self.profiles = [{"name": "Home VPN", "kind": "vpn", "active": False,
                          "uuid": "11111111-2222-3333-4444-555555555555"}]
        self.bt = {"powered": True, "adapter": "/org/bluez/hci0", "devices": [
            {"label": "Headset", "address": "AA:BB:CC:DD:EE:FF",
             "paired": True, "connected": False}]}
        self.presets = []
        self.preset_error = None
        self.fail = None          # exception raised by the next mutation
        self.gate = None          # Event a mutation waits on (busy tests)
        self.calls = []

    def mutate(self, name, apply):
        self.calls.append(name)
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail is not None:
            raise self.fail
        return apply()

    # --- reads -----------------------------------------------------------
    def wifi_snapshot(self, rescan=False):
        if self.wifi_error is not None:
            raise self.wifi_error
        return {"enabled": self.wifi, "networks": list(self.networks)}

    def connection_profiles(self):
        return [dict(item) for item in self.profiles]

    def bluetooth_snapshot(self):
        return {"powered": self.bt["powered"], "adapter": self.bt["adapter"],
                "devices": [dict(item) for item in self.bt["devices"]]}

    def timezone_snapshot(self):
        return {"current": "UTC", "zones": ("UTC",)}

    def ntp_snapshot(self):
        return {"available": True, "enabled": self.ntp}

    # --- mutations -------------------------------------------------------
    def set_wifi(self, enabled, *, expected):
        def apply():
            self.wifi = enabled
            return enabled
        return self.mutate("set_wifi", apply)

    def set_ntp(self, enabled, *, expected):
        def apply():
            self.ntp = enabled
            return {"available": True, "enabled": enabled}
        return self.mutate("set_ntp", apply)

    def set_system_clock(self, value, *, expected_ntp=False):
        def apply():
            self.clock_ntp_value = value
            return value
        return self.mutate("set_system_clock", apply)

    def set_connection_profile(self, uuid, enabled, *, expected):
        def apply():
            for item in self.profiles:
                if item["uuid"] == uuid:
                    item["active"] = enabled
            return dict(self.profiles[0])
        return self.mutate("set_connection_profile", apply)

    def set_bluetooth_power(self, enabled, *, expected, expected_adapter=None):
        def apply():
            self.bt["powered"] = enabled
            return self.bluetooth_snapshot()
        return self.mutate("set_bluetooth_power", apply)

    def set_bluetooth_connection(self, address, connected, *, expected,
                                 expected_adapter=None):
        def apply():
            for item in self.bt["devices"]:
                if item["address"] == address:
                    item["connected"] = connected
            return self.bluetooth_snapshot()
        return self.mutate("set_bluetooth_connection", apply)

    # --- display presets -------------------------------------------------
    def preset_load(self):
        if self.preset_error is not None:
            raise self.preset_error
        return [dict(item) for item in self.presets]

    def preset_save(self, entries, *, expected):
        def apply():
            self.presets = [dict(item) for item in entries]
            return entries
        return self.mutate("preset_save", apply)


class _GuiCase(unittest.TestCase):
    def setUp(self):
        try:
            self.Gtk, Gdk, self.GLib = settings._gtk_modules()
        except (ImportError, ValueError):
            self.skipTest("GTK introspection typelib is not installed")
        if not self.Gtk.init_check([])[0]:
            self.skipTest("GTK display is unavailable")
        self.fake = FakeAdapters()
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("wifi_snapshot", "connection_profiles", "bluetooth_snapshot",
                     "timezone_snapshot", "ntp_snapshot", "set_wifi", "set_ntp",
                     "set_system_clock", "set_connection_profile",
                     "set_bluetooth_power", "set_bluetooth_connection"):
            stack.enter_context(mock.patch.object(backend, name, getattr(self.fake, name)))
        stack.enter_context(mock.patch.object(backend, "external_tool", return_value=None))
        stack.enter_context(mock.patch.object(settings.wayland_displays, "_in_session",
                                              return_value=True))
        stack.enter_context(mock.patch.object(
            settings.wayland_displays, "inventory",
            return_value=(Output("HDMI-A-1", "1920x1080@60.000Hz", ("1920x1080@60.000Hz",), 1.0),)))
        stack.enter_context(mock.patch.object(settings.display_presets, "load",
                                              self.fake.preset_load))
        stack.enter_context(mock.patch.object(settings.display_presets, "save",
                                              self.fake.preset_save))
        stack.enter_context(mock.patch.object(settings.display_presets,
                                              "auto_trial_enabled", return_value=False))
        stack.enter_context(mock.patch.object(settings.display_restore, "plan",
                                              return_value=None))
        # Confirmation dialogs are real widgets in production; answer them here.
        self.answer = self.Gtk.ResponseType.YES
        stack.enter_context(mock.patch.object(
            self.Gtk.MessageDialog, "run", lambda _dialog: self.answer))
        self.window = settings.RiceSpiceWindow(self.Gtk, Gdk, self.GLib)
        self.addCleanup(self._close)
        self.pump(lambda: not self.window.busy)

    def _close(self):
        if self.fake.gate is not None:
            self.fake.gate.set()
        with mock.patch.object(self.Gtk, "main_quit"):   # no Gtk.main() is running
            self.window.window.destroy()
        self.pump(lambda: False, limit=5)

    def pump(self, condition, limit=400):
        """Run the GTK main context with a hard bound (about 2 s worst case)."""
        context = self.GLib.MainContext.default()
        for _ in range(limit):
            while context.pending():
                context.iteration(False)
            if condition():
                return True
            time.sleep(0.005)
        return condition()

    def widgets(self):
        found, queue = [], [self.window.content]
        while queue:
            widget = queue.pop()
            found.append(widget)
            if isinstance(widget, self.Gtk.Container):
                queue.extend(widget.get_children())
        return found

    def button(self, label):
        return next((w for w in self.widgets() if isinstance(w, self.Gtk.Button)
                     and w.get_label() == label), None)

    def texts(self):
        return [w.get_text() for w in self.widgets() if isinstance(w, self.Gtk.Label)]

    def status(self):
        return self.window.status.get_text()

    def open_page(self, page, ready_label):
        self.window.show_page(page)
        self.assertTrue(self.pump(lambda: self.button(ready_label) is not None),
                        f"{page} page never showed {ready_label!r}")
        self.assertFalse(self.window.busy)

    def click(self, label):
        button = self.button(label)
        self.assertIsNotNone(button, f"missing button {label!r}")
        self.assertTrue(button.get_sensitive())
        button.clicked()

    def settle(self):
        self.assertTrue(self.pump(lambda: not self.window.busy), "worker never finished")

    # The five-state matrix shared by every mutating control ---------------
    def drive_failure(self, page, label, exc, expected_text):
        self.open_page(page, label)
        self.fake.fail = exc
        self.click(label)
        self.assertTrue(self.pump(lambda: self.status() == expected_text),
                        f"status was {self.status()!r}")
        self.settle()
        self.pump(lambda: False, limit=10)   # a replay would show up here
        self.assertEqual(len(self.fake.calls), 1, "failed write must never be replayed")
        button = self.button(label)
        self.assertIsNotNone(button, "page must keep the original control after failure")
        self.assertTrue(button.get_sensitive(), "control must not stay latched busy")
        self.assertEqual(self.status(), expected_text)

    def drive_busy(self, page, label, after_label):
        self.open_page(page, label)
        self.fake.gate = threading.Event()
        self.click(label)
        self.assertTrue(self.window.busy)
        self.assertTrue(self.pump(lambda: len(self.fake.calls) == 1))
        self.button(label).clicked()          # second click while in flight
        self.assertIn("retry this action", self.status())
        self.pump(lambda: False, limit=10)
        self.assertEqual(len(self.fake.calls), 1, "busy click must not reach the backend")
        self.fake.gate.set()
        self.assertTrue(self.pump(lambda: self.button(after_label) is not None))
        self.settle()
        self.assertEqual(len(self.fake.calls), 1)

    def drive_matrix(self, page, label, after_label, check_success, stale_text,
                     generic_text="Backend refused", reset=None):
        """Run denied, generic, stale and busy against fresh windows state."""
        cases = (
            ("denied", backend.SettingsDenied(), authorization.DENIED_MESSAGE),
            ("generic", backend.SettingsError(generic_text),
             "Unavailable or denied: " + generic_text),
            ("stale", backend.SettingsError(stale_text),
             "Unavailable or denied: " + stale_text),
        )
        for name, exc, expected in cases:
            with self.subTest(outcome=name):
                self.fake.calls.clear()
                self.fake.fail = None
                if reset:
                    reset()
                self.drive_failure(page, label, exc, expected)
        with self.subTest(outcome="busy"):
            self.fake.calls.clear()
            self.fake.fail = None
            if reset:
                reset()
            self.drive_busy(page, label, after_label)
            check_success()
        with self.subTest(outcome="success"):
            self.fake.calls.clear()
            self.fake.fail = None
            self.fake.gate = None
            if reset:
                reset()
            self.open_page(page, label)
            self.click(label)
            self.assertTrue(self.pump(lambda: self.button(after_label) is not None))
            self.settle()
            self.assertEqual(len(self.fake.calls), 1)
            check_success()


class NetworkControlTests(_GuiCase):
    def test_wifi_radio_toggle_all_outcomes(self):
        def reset():
            self.fake.wifi = True

        def success():
            self.assertTrue(self.pump(lambda: self.status() == "Wi-Fi radio: disabled"),
                            self.status())
            self.assertFalse(self.fake.wifi)
            self.assertIn("Enable Wi-Fi to look for networks.", self.texts())

        self.drive_matrix("network", "Disable Wi-Fi", "Enable Wi-Fi", success,
                          "Wi-Fi radio may have changed; outcome unknown; refresh",
                          reset=reset)

    def test_wifi_radio_enable_shows_enabled_readback(self):
        self.fake.wifi = False
        self.open_page("network", "Enable Wi-Fi")
        self.click("Enable Wi-Fi")
        self.assertTrue(self.pump(lambda: self.button("Disable Wi-Fi") is not None))
        self.assertTrue(self.pump(lambda: self.status() == "Wi-Fi radio: enabled"))

    def test_saved_profile_activation_all_outcomes(self):
        def reset():
            self.fake.profiles[0]["active"] = False

        def success():
            self.assertTrue(self.pump(
                lambda: "Home VPN · vpn · Connected" in self.texts()), self.texts())
            self.assertTrue(self.fake.profiles[0]["active"])

        self.drive_matrix("network", "Connect Home VPN", "Disconnect Home VPN", success,
                          "Network profile may have changed; provider verification "
                          "failed; refresh", reset=reset)

    def test_saved_profile_declined_confirmation_never_calls_backend(self):
        self.open_page("network", "Connect Home VPN")
        self.answer = self.Gtk.ResponseType.NO
        self.click("Connect Home VPN")
        self.pump(lambda: False, limit=10)
        self.assertEqual(self.fake.calls, [])
        self.assertFalse(self.window.busy)
        self.assertIn("Home VPN · vpn · Disconnected", self.texts())

    def test_wifi_scan_provider_error_is_not_an_empty_list(self):
        self.fake.wifi_error = backend.SettingsError("NetworkManager is not running")
        self.window.show_page("network")
        self.assertTrue(self.pump(lambda: any(
            "Wi-Fi radio/scan unavailable: NetworkManager is not running" in text
            for text in self.texts())), self.texts())
        self.assertIsNone(self.button("Disable Wi-Fi"))
        self.assertIsNone(self.button("Enable Wi-Fi"))
        self.assertFalse(any("No networks reported" in text for text in self.texts()))
        self.assertTrue(self.button("Refresh visible networks").get_sensitive())

    def test_wifi_scan_empty_result_says_so_and_offers_refresh(self):
        self.window.show_page("network")
        self.assertTrue(self.pump(lambda: any(
            text.startswith("No networks reported") for text in self.texts())), self.texts())
        self.assertFalse(any("unavailable" in text for text in self.texts()
                             if text.startswith("Wi-Fi radio")))
        self.assertTrue(self.button("Disable Wi-Fi").get_sensitive())
        self.assertTrue(self.button("Refresh visible networks").get_sensitive())


class BluetoothControlTests(_GuiCase):
    def test_bluetooth_power_all_outcomes(self):
        def reset():
            self.fake.bt["powered"] = True

        def success():
            self.assertTrue(self.pump(lambda: self.status() == "Bluetooth adapter: off"),
                            self.status())
            self.assertFalse(self.fake.bt["powered"])
            # Device actions are withdrawn while the adapter is off.
            self.assertIsNone(self.button("Connect"))

        self.drive_matrix("bluetooth", "Turn Bluetooth off", "Turn Bluetooth on", success,
                          "Bluetooth power may have changed; outcome unknown; refresh",
                          reset=reset)

    def test_bluetooth_device_connect_all_outcomes(self):
        def reset():
            self.fake.bt["devices"][0]["connected"] = False

        def success():
            self.assertTrue(self.pump(lambda: "Headset · connected" in self.texts()),
                            self.texts())
            self.assertTrue(self.fake.bt["devices"][0]["connected"])

        self.drive_matrix("bluetooth", "Connect", "Disconnect", success,
                          "Bluetooth device may have changed; outcome unknown; refresh",
                          reset=reset)

    def test_bluetooth_disconnect_shows_disconnected_readback(self):
        self.fake.bt["devices"][0]["connected"] = True
        self.open_page("bluetooth", "Disconnect")
        self.click("Disconnect")
        self.assertTrue(self.pump(lambda: "Headset · disconnected" in self.texts()))
        self.assertIsNotNone(self.button("Connect"))


class TimeControlTests(_GuiCase):
    def test_ntp_toggle_disable_all_outcomes(self):
        def reset():
            self.fake.ntp = True

        def success():
            self.assertTrue(self.pump(lambda: "Current state: disabled" in self.texts()),
                            self.texts())
            self.assertFalse(self.fake.ntp)
            # Manual clock entry only appears once the readback says NTP is off.
            self.assertIsNotNone(self.button("Set system date/time…"))

        self.drive_matrix("timezone", "Disable automatic time", "Enable automatic time",
                          success, UNKNOWN, reset=reset)

    def test_ntp_enable_busy_and_success_readback(self):
        self.fake.ntp = False
        self.open_page("timezone", "Enable automatic time")
        self.fake.gate = threading.Event()
        self.click("Enable automatic time")
        self.assertTrue(self.pump(lambda: len(self.fake.calls) == 1))
        self.button("Enable automatic time").clicked()
        self.assertIn("retry this action", self.status())
        self.fake.gate.set()
        self.assertTrue(self.pump(lambda: self.button("Disable automatic time") is not None))
        self.assertIn("Current state: enabled", self.texts())
        self.assertIsNone(self.button("Set system date/time…"))
        self.assertEqual(self.fake.calls, ["set_ntp"])

    def test_ntp_disable_declined_never_calls_backend(self):
        self.open_page("timezone", "Disable automatic time")
        self.answer = self.Gtk.ResponseType.NO
        self.click("Disable automatic time")
        self.pump(lambda: False, limit=10)
        self.assertEqual(self.fake.calls, [])
        self.assertIn("Current state: enabled", self.texts())

    def _clock_entry(self):
        return next(w for w in self.widgets() if isinstance(w, self.Gtk.Entry)
                    and not isinstance(w, self.Gtk.SearchEntry))

    def _type_clock(self, value="2030-01-02 03:04:05"):
        self._clock_entry().set_text(value)

    def test_manual_clock_all_outcomes(self):
        self.fake.ntp = False
        label = "Set system date/time…"
        self.open_page("timezone", label)
        cases = (
            ("denied", backend.SettingsDenied(), authorization.DENIED_MESSAGE),
            ("generic", backend.SettingsError("Backend refused"),
             "Unavailable or denied: Backend refused"),
            ("stale", backend.SettingsError(
                "System time may have changed; outcome unknown; refresh before retrying"),
             "Unavailable or denied: System time may have changed; outcome unknown; "
             "refresh before retrying"))
        for name, exc, expected in cases:
            with self.subTest(outcome=name):
                self.fake.calls.clear()
                self.fake.fail = exc
                self._type_clock()
                self.click(label)
                self.assertTrue(self.pump(lambda: self.status() == expected), self.status())
                self.settle()
                self.pump(lambda: False, limit=10)
                self.assertEqual(self.fake.calls, ["set_system_clock"])
                self.assertTrue(self.button(label).get_sensitive())
                self.assertEqual(self._clock_entry().get_text(), "2030-01-02 03:04:05")
        with self.subTest(outcome="busy"):
            self.fake.calls.clear()
            self.fake.fail = None
            self.fake.gate = threading.Event()
            self.click(label)
            self.assertTrue(self.pump(lambda: len(self.fake.calls) == 1))
            self.button(label).clicked()
            self.assertIn("retry this action", self.status())
            self.pump(lambda: False, limit=10)
            self.assertEqual(self.fake.calls, ["set_system_clock"])
            self.fake.gate.set()
            self.assertTrue(self.pump(lambda: self.fake.clock_ntp_value is not None
                                      and "verified" in self.status()), self.status())
            self.settle()
            self.assertEqual(self.fake.calls, ["set_system_clock"])
        with self.subTest(outcome="success"):
            # The verified backend value is shown, and NTP stays off in the readback.
            self.assertIn("System clock set and verified: 2030-01-02 03:04:05",
                          self.status())
            self.assertIn("Current state: disabled", self.texts())

    def test_manual_clock_incomplete_value_is_rejected_before_backend(self):
        self.fake.ntp = False
        self.open_page("timezone", "Set system date/time…")
        self._type_clock("2030-01-02")
        self.click("Set system date/time…")
        self.assertIn("Enter a complete local date/time", self.status())
        self.assertEqual(self.fake.calls, [])

    def test_manual_clock_declined_confirmation_never_calls_backend(self):
        self.fake.ntp = False
        self.open_page("timezone", "Set system date/time…")
        self._type_clock()
        self.answer = self.Gtk.ResponseType.NO
        self.click("Set system date/time…")
        self.pump(lambda: False, limit=10)
        self.assertEqual(self.fake.calls, [])


class DisplayPresetControlTests(_GuiCase):
    ENTRY = {"name": "HDMI-A-1", "mode": "1920x1080@60.000Hz", "scale": 1.0, "x": 0, "y": 0}

    def test_save_preset_success_shows_saved_layout(self):
        self.open_page("displays", "Save current layout as preset")
        self.click("Save current layout as preset")
        self.assertTrue(self.pump(lambda: self.button("Forget saved monitor layout")
                                  is not None))
        self.assertEqual(self.fake.presets, [self.ENTRY])
        self.assertIn("HDMI-A-1 · 1920x1080@60.000Hz · 1× · 0,0", self.texts())

    def test_forget_preset_success_clears_the_layout(self):
        self.fake.presets = [dict(self.ENTRY)]
        self.open_page("displays", "Forget saved monitor layout")
        self.click("Forget saved monitor layout")
        self.assertTrue(self.pump(lambda: "No monitor layout has been saved." in self.texts()),
                        self.texts())
        self.assertEqual(self.fake.presets, [])
        self.assertIsNone(self.button("Forget saved monitor layout"))

    def test_stale_and_write_failures_are_visible_and_keep_the_saved_layout(self):
        # The real store raises ValueError for a stale expected preset.
        stale = ValueError("Saved monitor layout changed; refresh before replacing")
        for label, preset in (("Save current layout as preset", []),
                              ("Forget saved monitor layout", [dict(self.ENTRY)])):
            for exc in (stale, OSError("disk full")):
                with self.subTest(button=label, error=type(exc).__name__):
                    self.fake.presets = [dict(item) for item in preset]
                    self.fake.calls.clear()
                    self.fake.fail = exc
                    self.open_page("displays", label)
                    self.click(label)
                    expected = settings.denial_or_error_text(exc)
                    self.assertTrue(self.pump(lambda: self.status() == expected),
                                    self.status())
                    self.settle()
                    self.assertEqual(self.fake.calls, ["preset_save"])
                    self.assertEqual(self.fake.presets, preset)
                    self.assertTrue(self.button(label).get_sensitive())

    def test_preset_busy_second_click_refused(self):
        self.fake.presets = [dict(self.ENTRY)]
        self.open_page("displays", "Forget saved monitor layout")
        self.fake.gate = threading.Event()
        self.click("Forget saved monitor layout")
        self.assertTrue(self.pump(lambda: len(self.fake.calls) == 1))
        self.button("Forget saved monitor layout").clicked()
        self.assertIn("retry this action", self.status())
        self.pump(lambda: False, limit=10)
        self.assertEqual(self.fake.calls, ["preset_save"])
        self.fake.gate.set()
        self.assertTrue(self.pump(lambda: "No monitor layout has been saved." in self.texts()))

    def test_unreadable_preset_store_offers_no_save_or_forget(self):
        self.fake.preset_error = ValueError("Unsafe monitor preset file")
        self.window.show_page("displays")
        self.assertTrue(self.pump(lambda: any(
            "Saved monitor layout unavailable: Unsafe monitor preset file" in text
            for text in self.texts())), self.texts())
        self.assertIsNone(self.button("Save current layout as preset"))
        self.assertIsNone(self.button("Forget saved monitor layout"))


if __name__ == "__main__":
    unittest.main()
