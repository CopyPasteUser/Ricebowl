"""SG2 WP2.2 gap fill: real-Gtk RiceSpice pages for input/accessibility prefs
(I1/I2/I3) and the next-login monitor trial toggle (D5).

Reuses the headless harness of ``test_de_settings_gui_controls`` (real widgets,
real worker/idle path); only the preferences / presets storage boundary is
replaced. GTK tests skip without the typelib or a display.
"""
import unittest
from unittest import mock

from macrice import authorization
from macrice.de import preferences, settings
from macrice.de import settings_backend as backend
from macrice.de.display_presets import auto_trial_enabled  # noqa: F401  (import check)
from tests.test_de_settings_gui_controls import _GuiCase

SAVE = "Save for next RiceBowl login"


class FakePreferences:
    def __init__(self):
        self.values = dict(preferences.DEFAULTS)
        self.load_error = None
        self.save_error = None
        self.saved = []

    def load(self):
        if self.load_error is not None:
            raise self.load_error
        return dict(self.values)

    def save(self, requested, *, expected):
        self.saved.append(dict(requested))
        if self.save_error is not None:
            raise self.save_error
        if dict(expected) != self.values:
            raise preferences.PreferenceError(
                "Preferences changed elsewhere; refresh before applying")
        self.values = dict(requested)
        return dict(requested)


class PreferencePageTests(_GuiCase):
    def setUp(self):
        super().setUp()
        self.prefs = FakePreferences()
        for name in ("load", "save"):
            patcher = mock.patch.object(settings.preferences, name,
                                        getattr(self.prefs, name))
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_input_and_accessibility_save_shows_next_login_state_and_readback(self):
        for page in ("input", "accessibility"):
            with self.subTest(page=page):
                self.prefs.values = dict(preferences.DEFAULTS)
                self.prefs.saved.clear()
                self.open_page(page, SAVE)
                self.assertIn("Currently using inherited settings", self.status())
                self.assertTrue(any("only the next RiceBowl Wayland login" in text
                                    for text in self.texts()))
                self.click(SAVE)
                flag = "input_enabled" if page == "input" else "accessibility_enabled"
                self.assertTrue(self.pump(lambda: self.prefs.values[flag] is True))
                self.assertTrue(self.pump(
                    lambda: self.button("Restore inherited settings for next login")
                    is not None), self.texts())
                self.assertIn("RiceBowl overrides enabled", self.status())
                self.settle()
                self.assertEqual(len(self.prefs.saved), 1)

    def test_preference_errors_are_visible_and_not_replayed(self):
        cases = (
            preferences.PreferenceError("Preferences changed elsewhere; refresh before applying"),
            OSError("disk full"),
            backend.SettingsDenied(),
        )
        for page in ("input", "accessibility"):
            for exc in cases:
                with self.subTest(page=page, error=type(exc).__name__):
                    self.prefs.values = dict(preferences.DEFAULTS)
                    self.prefs.saved.clear()
                    self.prefs.save_error = exc
                    self.open_page(page, SAVE)
                    self.click(SAVE)
                    expected = settings.denial_or_error_text(exc)
                    self.assertTrue(self.pump(lambda: self.status() == expected),
                                    self.status())
                    self.settle()
                    self.pump(lambda: False, limit=10)
                    self.assertEqual(len(self.prefs.saved), 1, "no replay")
                    self.assertEqual(self.prefs.values, dict(preferences.DEFAULTS))
                    self.assertTrue(self.button(SAVE).get_sensitive())

    def test_unreadable_preference_store_offers_no_save(self):
        for page in ("input", "accessibility"):
            with self.subTest(page=page):
                self.prefs.load_error = preferences.PreferenceError(
                    "Unsafe RiceSpice preference file")
                self.window.show_page(page)
                self.assertTrue(self.pump(lambda: "Private RiceSpice preferences "
                                          "unavailable: Unsafe RiceSpice preference file"
                                          == self.status()), self.status())
                self.assertIsNone(self.button(SAVE))

    def test_i3_missing_orca_is_stated_not_hidden(self):
        for installed, wanted in ((None, "Orca is not installed"),
                                  ("/usr/bin/orca", "Orca is installed")):
            with self.subTest(orca=installed):
                with mock.patch.object(settings.shutil, "which",
                                       return_value=installed):
                    self.open_page("accessibility", SAVE)
                self.assertTrue(any(text.startswith(wanted) for text in self.texts()),
                                self.texts())


class NextLoginMonitorTrialTests(_GuiCase):
    ENTRY = {"name": "HDMI-A-1", "mode": "1920x1080@60.000Hz", "scale": 1.0,
             "x": 0, "y": 0}

    def setUp(self):
        super().setUp()
        self.fake.presets = [dict(self.ENTRY)]
        self.enabled = False
        self.toggles = []
        patcher = mock.patch.object(settings.display_presets, "auto_trial_enabled",
                                    lambda: self.enabled)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(settings.display_presets, "set_auto_trial",
                                    self.set_auto_trial)
        patcher.start()
        self.addCleanup(patcher.stop)

    def set_auto_trial(self, enabled, *, expected):
        def apply():
            self.toggles.append((enabled, expected))
            self.enabled = enabled
            return enabled
        return self.fake.mutate("set_auto_trial", apply)

    def test_d5_toggle_shows_verified_state_after_enable_and_disable(self):
        self.open_page("displays", "Enable next-login monitor trial")
        self.click("Enable next-login monitor trial")
        self.assertTrue(self.pump(lambda: self.button("Disable next-login monitor trial")
                                  is not None), self.texts())
        self.click("Disable next-login monitor trial")
        self.assertTrue(self.pump(lambda: self.button("Enable next-login monitor trial")
                                  is not None), self.texts())
        self.assertEqual(self.toggles, [(True, False), (False, True)])

    def test_d5_stale_and_write_failures_are_visible_and_not_replayed(self):
        for exc in (ValueError("Automatic monitor trial setting changed; refresh first"),
                    OSError("disk full")):
            with self.subTest(error=type(exc).__name__):
                self.enabled = False
                self.toggles.clear()
                self.fake.calls.clear()
                self.fake.fail = exc
                self.open_page("displays", "Enable next-login monitor trial")
                self.click("Enable next-login monitor trial")
                expected = settings.denial_or_error_text(exc)
                self.assertTrue(self.pump(lambda: self.status() == expected), self.status())
                self.settle()
                self.pump(lambda: False, limit=10)
                self.assertEqual(self.fake.calls, ["set_auto_trial"])
                self.assertEqual(self.toggles, [])
                self.assertFalse(self.enabled)
                self.assertTrue(self.button("Enable next-login monitor trial")
                                .get_sensitive())

    def test_d5_toggle_absent_without_a_saved_layout(self):
        self.fake.presets = []
        self.window.show_page("displays")
        self.assertTrue(self.pump(lambda: "No monitor layout has been saved."
                                  in self.texts()), self.texts())
        self.assertIsNone(self.button("Enable next-login monitor trial"))
        self.assertIsNone(self.button("Disable next-login monitor trial"))


class _EnrollmentAudioBase(_GuiCase):
    """Shared three-outcome driver: success, typed denial, generic error."""

    def setUp(self):
        super().setUp()
        self.patch(self.Gtk.Dialog, "run", lambda _dialog: self.Gtk.ResponseType.OK)

    def patch(self, target, name, value):
        patcher = mock.patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def drive_outcomes(self, page, label, success_check):
        cases = (
            (backend.SettingsDenied(), authorization.DENIED_MESSAGE),
            (backend.SettingsError("Backend refused"),
             "Unavailable or denied: Backend refused"),
        )
        for exc, expected in cases:
            with self.subTest(outcome=type(exc).__name__):
                self.fake.calls.clear()
                self.fake.fail = exc
                self.open_page(page, label)
                self.click(label)
                self.assertTrue(self.pump(lambda: self.status() == expected), self.status())
                self.settle()
                self.pump(lambda: False, limit=10)
                self.assertEqual(len(self.fake.calls), 1, "no replay")
                self.assertTrue(self.button(label).get_sensitive())
        with self.subTest(outcome="success"):
            self.fake.calls.clear()
            self.fake.fail = None
            self.open_page(page, label)
            self.click(label)
            self.assertTrue(self.pump(lambda: len(self.fake.calls) == 1))
            self.settle()
            success_check()
            self.assertEqual(len(self.fake.calls), 1)


class EnrollmentDialogTests(_EnrollmentAudioBase):
    """N5/N6/N7: enterprise create, enterprise connect and VPN import flows."""

    def test_n5_enterprise_create_shows_denial_error_and_success_once(self):
        created = []

        def create(**kwargs):
            return self.fake.mutate("create_enterprise_wifi",
                                    lambda: created.append(kwargs) or "uuid")

        self.patch(settings.network_enrollment, "create_enterprise_wifi", create)
        self.drive_outcomes("network", "Add enterprise Wi-Fi profile…",
                            lambda: self.assertEqual(len(created), 1))

    def test_n5_unknown_outcome_text_is_shown_and_never_replayed(self):
        text = ("Enterprise profile creation outcome unknown; refresh saved profiles "
                "before retrying")
        self.patch(settings.network_enrollment, "create_enterprise_wifi",
                   lambda **_kw: self.fake.mutate(
                       "create_enterprise_wifi", lambda: None))
        self.fake.fail = backend.SettingsError(text)
        self.open_page("network", "Add enterprise Wi-Fi profile…")
        self.click("Add enterprise Wi-Fi profile…")
        self.assertTrue(self.pump(lambda: self.status() == "Unavailable or denied: " + text),
                        self.status())
        self.settle()
        self.assertEqual(len(self.fake.calls), 1)

    def test_n6_enterprise_connect_shows_denial_error_and_success_once(self):
        label = "Connect with 802.1X password: Corp"
        self.fake.profiles = [{"name": "Corp", "kind": "802-11-wireless",
                               "active": False,
                               "uuid": "11111111-2222-3333-4444-555555555555"}]
        connected = []
        self.patch(settings.network_enrollment, "enterprise_password_ready",
                   lambda _uuid: True)
        self.patch(settings.network_enrollment, "connect_enterprise_wifi",
                   lambda uuid, secret, expected_active: self.fake.mutate(
                       "connect_enterprise_wifi",
                       lambda: connected.append(uuid) or True))
        self.drive_outcomes("network", label,
                            lambda: self.assertEqual(len(connected), 1))

    def test_n7_vpn_import_shows_denial_error_and_success_once(self):
        imported = []
        self.patch(self.Gtk.FileChooserDialog, "get_filename",
                   lambda _chooser: "/tmp/office.ovpn")
        self.patch(settings.network_enrollment, "import_vpn_profile",
                   lambda path: self.fake.mutate(
                       "import_vpn_profile", lambda: imported.append(path) or "uuid"))
        self.drive_outcomes("network", "Import OpenVPN / WireGuard profile…",
                            lambda: self.assertEqual(imported, ["/tmp/office.ovpn"]))

    def test_n7_cancelled_chooser_never_reaches_backend(self):
        self.patch(self.Gtk.Dialog, "run", lambda _dialog: self.Gtk.ResponseType.CANCEL)
        self.patch(settings.network_enrollment, "import_vpn_profile",
                   lambda path: self.fail("cancel must not import"))
        self.open_page("network", "Import OpenVPN / WireGuard profile…")
        self.click("Import OpenVPN / WireGuard profile…")
        self.pump(lambda: False, limit=10)
        self.assertFalse(self.window.busy)


class AudioDefaultControlTests(_EnrollmentAudioBase):
    """A1: default sink/source buttons show verified, denied and error states."""

    def setUp(self):
        super().setUp()
        self.defaults = {"sink": "alsa_out.a", "source": "alsa_in.a"}
        self.inventory = lambda: {
            "outputs": [{"name": "alsa_out.a", "description": "Speakers",
                         "default": self.defaults["sink"] == "alsa_out.a"},
                        {"name": "alsa_out.b", "description": "HDMI",
                         "default": self.defaults["sink"] == "alsa_out.b"}],
            "inputs": [{"name": "alsa_in.a", "description": "Mic",
                        "default": True}]}
        self.patch(settings.audio_devices, "inspect", lambda: self.inventory())
        self.patch(settings.audio_devices, "playback_streams",
                   lambda: {"streams": []})
        self.patch(settings.media, "read_media_players", lambda: [])
        self.set_calls = []
        self.patch(settings.audio_devices, "set_default",
                   lambda kind, name, expected_current: self.fake.mutate(
                       "set_default", lambda: self.set_calls.append((kind, name))))

    def test_a1_default_output_denial_error_and_unavailable_provider(self):
        self.drive_outcomes("audio", "Set default output",
                            lambda: self.assertEqual(
                                self.set_calls, [("sink", "alsa_out.a")]))

    def test_a1_provider_error_is_visible_and_offers_no_control(self):
        def broken():
            raise RuntimeError("PulseAudio is not running")

        self.patch(settings.audio_devices, "inspect", broken)
        self.window.show_page("audio")
        self.assertTrue(self.pump(lambda: any(
            "Audio devices unavailable: PulseAudio is not running" in text
            for text in self.texts())), self.texts())
        self.assertIsNone(self.button("Set default output"))
        self.assertIsNone(self.button("Set default microphone"))


if __name__ == "__main__":
    unittest.main()
