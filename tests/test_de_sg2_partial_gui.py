"""SG2 WP2.3: real-Gtk evidence for the inventory GUI cells that were `~`.

A2/A3/A4 per-application audio streams, P1 energy profile, P2 lock screen,
N5 busy and D1/D4 monitor trials. Same harness as
``test_de_sg2_gap_gui``: real widgets and worker/idle path, fake adapters at the
module boundary. GTK tests skip without the typelib or a display.
"""
import unittest
from unittest import mock

from macrice import authorization
from macrice.de import settings
from macrice.de import settings_backend as backend
from macrice.de.audio_devices import AudioDeviceError
from tests.test_de_sg2_gap_gui import _EnrollmentAudioBase
from tests.test_de_settings_gui_controls import _GuiCase

CLIENT = 42


class StreamControlTests(_EnrollmentAudioBase):
    """A2/A3/A4: stream output, volume and mute show every outcome, once."""

    def setUp(self):
        super().setUp()
        self.stream = {"index": 7, "label": "Player", "volume": 50, "mute": False,
                       "client": CLIENT, "sink": 1}
        self.stream_state = lambda: {
            "streams": [dict(self.stream)],
            "outputs": [{"name": "alsa_out.a", "description": "Speakers", "index": 1},
                        {"name": "alsa_out.b", "description": "HDMI", "index": 2}]}
        self.patch(settings.audio_devices, "inspect",
                   lambda: {"outputs": [], "inputs": []})
        self.patch(settings.audio_devices, "playback_streams",
                   lambda: self.stream_state())
        self.patch(settings.media, "read_media_players", lambda: [])
        self.moves, self.volumes, self.mutes = [], [], []

        def move(index, sink, *, expected_sink, expected_client):
            return self.fake.mutate("move", lambda: self.moves.append(
                (index, sink, expected_sink, expected_client)))

        def volume(index, percent, *, expected, expected_client):
            def apply():
                self.volumes.append((index, percent, expected, expected_client))
                self.stream["volume"] = percent
            return self.fake.mutate("volume", apply)

        def mute(index, enabled, *, expected, expected_client):
            def apply():
                self.mutes.append((index, enabled, expected, expected_client))
                self.stream["mute"] = enabled
            return self.fake.mutate("mute", apply)

        self.patch(settings.audio_devices, "set_stream_output", move)
        self.patch(settings.audio_devices, "set_stream_volume", volume)
        self.patch(settings.audio_devices, "set_stream_mute", mute)

    def test_a2_move_stream_denial_error_and_verified_identity(self):
        self.drive_outcomes("audio", "Move Player to selected output",
                            lambda: self.assertEqual(
                                self.moves, [(7, "alsa_out.a", 1, CLIENT)]))

    def test_a3_stream_volume_denial_error_and_rendered_result(self):
        self.drive_outcomes("audio", "Set Player volume",
                            lambda: self.assertEqual(
                                self.volumes, [(7, 50, 50, CLIENT)]))

    def test_a4_stream_mute_denial_error_and_rendered_result(self):
        def success():
            self.assertEqual(self.mutes, [(7, True, False, CLIENT)])
            self.assertTrue(self.pump(
                lambda: "Player · 50% · Muted" in self.texts()), self.texts())
            self.assertIsNotNone(self.button("Unmute Player"))

        self.drive_outcomes("audio", "Mute Player", success)

    def test_a2_a4_stale_client_error_is_shown_and_not_replayed(self):
        error = AudioDeviceError("Audio stream changed owner; refresh before applying",
                                 "stale_audio_stream")
        for label in ("Move Player to selected output", "Mute Player"):
            with self.subTest(control=label):
                self.fake.calls.clear()
                self.fake.fail = error
                self.open_page("audio", label)
                self.click(label)
                expected = settings.denial_or_error_text(error)
                self.assertTrue(self.pump(lambda: self.status() == expected), self.status())
                self.settle()
                self.pump(lambda: False, limit=10)
                self.assertEqual(len(self.fake.calls), 1)
                self.assertTrue(self.button(label).get_sensitive())

    def test_a4_busy_second_click_is_refused_with_one_backend_call(self):
        self.drive_busy("audio", "Mute Player", "Unmute Player")

    def test_a2_a4_stream_without_verifiable_client_offers_no_control(self):
        self.stream["client"] = None
        self.window.show_page("audio")
        self.assertTrue(self.pump(lambda: any(
            "no verifiable audio client" in text for text in self.texts())),
            self.texts())
        for label in ("Move Player to selected output", "Set Player volume",
                      "Mute Player"):
            self.assertIsNone(self.button(label))

    def test_a2_a4_stream_provider_error_is_stated_not_an_empty_list(self):
        def broken():
            raise AudioDeviceError("PipeWire is not running")

        self.patch(settings.audio_devices, "playback_streams", broken)
        self.window.show_page("audio")
        self.assertTrue(self.pump(lambda: any(
            "Application playback controls unavailable: PipeWire is not running" in text
            for text in self.texts())), self.texts())
        self.assertFalse(any("No active playback streams" in t for t in self.texts()))


class PowerPageTests(_GuiCase):
    """P1 energy profile and P2 lock screen as rendered controls."""

    def setUp(self):
        super().setUp()
        self.profile = "balanced"
        self.supported = ["power-saver", "balanced", "performance"]
        self.snapshot_error = None
        self.applied, self.locks = [], []

        def snapshot():
            if self.snapshot_error is not None:
                raise self.snapshot_error
            return {"current": self.profile, "supported": list(self.supported),
                    "battery": None}

        def set_profile(name, *, expected):
            def apply():
                self.applied.append((name, expected))
                self.profile = name
                return name
            return self.fake.mutate("set_power_profile", apply)

        def power_action(action, nested=False):
            return self.fake.mutate("power_action", lambda: self.locks.append(action))

        for name, value in (("power_snapshot", snapshot),
                            ("set_power_profile", set_profile),
                            ("power_action", power_action)):
            patcher = mock.patch.object(backend, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def combo(self):
        return next((w for w in self.widgets()
                     if isinstance(w, self.Gtk.ComboBoxText)), None)

    def open_page(self, page, ready_label):
        super().open_page(page, ready_label)
        if page == "power" and ready_label == "Apply energy profile":
            self.combo().set_active_id("performance")

    def test_p1_energy_profile_all_outcomes_and_rendered_readback(self):
        def reset():
            self.profile = "balanced"
            self.applied.clear()

        def success():
            self.assertEqual(self.applied, [("performance", "balanced")])
            self.assertTrue(self.pump(
                lambda: self.combo() is not None
                and self.combo().get_active_id() == "performance"))

        self.drive_matrix(
            "power", "Apply energy profile", "Apply energy profile", success,
            "Power profile changed; refresh before applying", reset=reset)

    def test_p1_unknown_outcome_text_is_shown_and_never_replayed(self):
        text = "Power profile may have changed; outcome unknown; refresh"
        self.fake.calls.clear()
        self.fake.fail = backend.SettingsError(text)
        self.drive_failure("power", "Apply energy profile", self.fake.fail,
                           "Unavailable or denied: " + text)
        self.assertEqual(self.applied, [])

    def test_p1_missing_profile_service_offers_no_selector(self):
        self.profile, self.supported = "", []
        self.window.show_page("power")
        self.assertTrue(self.pump(lambda: any(
            "No supported power-profile service" in text for text in self.texts())),
            self.texts())
        self.assertIsNone(self.button("Apply energy profile"))
        self.assertIsNone(self.combo())

    def test_p1_provider_error_is_the_status_not_a_default_profile(self):
        self.snapshot_error = backend.SettingsError(
            "Power profile provider unavailable; refresh")
        self.window.show_page("power")
        self.assertTrue(self.pump(lambda: self.status() ==
                                  "Unavailable or denied: Power profile provider "
                                  "unavailable; refresh"), self.status())
        self.assertIsNone(self.button("Apply energy profile"))

    def test_p2_lock_screen_all_outcomes_without_overclaiming(self):
        def success():
            self.assertEqual(self.locks, ["lock"])
            self.assertTrue(self.pump(lambda: self.status() == "Lock screen launched"),
                            self.status())

        self.drive_matrix(
            "power", "Lock screen", "Lock screen", success,
            "Screen lock failed; suspend was not requested",
            reset=self.locks.clear)

    def test_p2_lock_never_says_locked_or_suspended(self):
        self.open_page("power", "Lock screen")
        self.click("Lock screen")
        self.assertTrue(self.pump(lambda: self.status() == "Lock screen launched"))
        self.settle()
        for text in self.texts() + [self.status()]:
            self.assertNotIn("suspend requested", text.lower())


class EnterpriseCreateBusyTests(_GuiCase):
    """N5 BUSY: a second click on the enterprise dialog never reaches the adapter."""

    def test_n5_second_click_while_creating_is_refused_with_one_call(self):
        patchers = [
            mock.patch.object(self.Gtk.Dialog, "run",
                              lambda _dialog: self.Gtk.ResponseType.OK),
            mock.patch.object(
                settings.network_enrollment, "create_enterprise_wifi",
                lambda **_kw: self.fake.mutate("create_enterprise_wifi", lambda: "uuid")),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.drive_busy("network", "Add enterprise Wi-Fi profile…",
                        "Add enterprise Wi-Fi profile…")


class DisplayTrialTests(_GuiCase):
    """D1/D4: guarded trials show started/kept/reverted/error states honestly."""

    ENTRY = {"name": "HDMI-A-1", "mode": "1920x1080@60.000Hz", "scale": 1.0,
             "x": 0, "y": 0}
    TRIALS = ("Try settings on HDMI-A-1", "Try entire saved monitor layout",
              "Try saved layout on HDMI-A-1")

    def setUp(self):
        super().setUp()
        self.fake.presets = [dict(self.ENTRY)]
        self.change = object()
        self.begun = []
        self.kept = []
        self.guard = [("pending", "Confirm within 18 seconds")]
        self.guard_error = None
        self.keep_error = None

        def begin(label):
            def run(*args, **kwargs):
                return self.fake.mutate(
                    label, lambda: self.begun.append(label) or self.change)
            return run

        def read_status(change):
            if self.guard_error is not None:
                raise self.guard_error
            return self.guard[0] if len(self.guard) == 1 else self.guard.pop(0)

        def keep_change(change):
            if self.keep_error is not None:
                raise self.keep_error
            self.kept.append(change)
            self.guard[:] = [("kept", "Settings kept")]

        for target, name, value in (
                (settings.wayland_displays, "begin_change", begin("begin_change")),
                (settings.display_restore, "begin", begin("restore")),
                (settings.display_guard, "read_status", read_status),
                (settings.display_guard, "keep_change", keep_change)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_d1_d4_trial_start_is_shown_then_kept_only_after_guard_confirms(self):
        for label in self.TRIALS:
            with self.subTest(trial=label):
                self.begun.clear()
                self.kept.clear()
                self.guard[:] = [("pending", "Confirm within 18 seconds")]
                self.fake.calls.clear()
                self.open_page("displays", label)
                self.click(label)
                keep = "Keep these display settings"
                self.assertTrue(self.pump(lambda: self.button(keep) is not None),
                                self.texts())
                self.assertEqual(len(self.begun), 1)
                self.assertTrue(self.pump(lambda: self.status().startswith(
                    "Display trial: pending.")), self.status())
                self.click(keep)
                self.assertEqual(self.kept, [self.change])
                self.assertTrue(self.pump(lambda: self.status() ==
                                          "Display trial: kept. Settings kept"),
                                self.status())
                self.assertFalse(self.button(keep).get_sensitive(),
                                 "no second confirmation after the guard is done")

    def test_d1_d4_guard_reverted_is_reported_and_keep_is_disabled(self):
        self.guard[:] = [("pending", "wait"), ("reverted", "Original mode restored")]
        self.open_page("displays", self.TRIALS[0])
        self.click(self.TRIALS[0])
        self.assertTrue(self.pump(lambda: self.status() ==
                                  "Display trial: reverted. Original mode restored"),
                        self.status())
        self.assertFalse(self.button("Keep these display settings").get_sensitive())
        self.assertEqual(self.kept, [])

    def test_d1_d4_guard_unavailable_says_rollback_is_automatic(self):
        self.guard_error = RuntimeError("Cannot read display guard status")
        self.open_page("displays", self.TRIALS[1])
        self.click(self.TRIALS[1])
        self.assertTrue(self.pump(lambda: self.status().startswith(
            "Display guard unavailable; wait for its automatic rollback:")),
            self.status())
        self.assertFalse(self.button("Keep these display settings").get_sensitive())

    def test_d1_d4_keep_failure_leaves_automatic_rollback_active(self):
        self.keep_error = RuntimeError("The display change is not waiting for confirmation")
        self.open_page("displays", self.TRIALS[2])
        self.click(self.TRIALS[2])
        self.assertTrue(self.pump(lambda: self.button("Keep these display settings")
                                  is not None))
        self.click("Keep these display settings")
        self.assertTrue(self.pump(lambda: self.status().startswith(
            "Could not confirm; automatic rollback remains active:")), self.status())
        self.assertEqual(self.kept, [])

    def test_d1_d4_stale_topology_and_start_failures_are_visible_not_replayed(self):
        for label in self.TRIALS:
            for exc in (ValueError("Monitor layout changed; refresh monitors"),
                        RuntimeError("compositor refused the output change")):
                with self.subTest(trial=label, error=type(exc).__name__):
                    self.fake.calls.clear()
                    self.begun.clear()
                    self.drive_failure("displays", label, exc,
                                       settings.denial_or_error_text(exc))
                    self.assertEqual(self.begun, [])
                    self.assertIsNone(self.button("Keep these display settings"),
                                      "a failed start must not offer Keep")

    def test_d1_d4_busy_second_trial_click_is_refused_with_one_call(self):
        for label in self.TRIALS:
            with self.subTest(trial=label):
                self.fake.calls.clear()
                self.guard[:] = [("pending", "wait")]
                self.drive_busy("displays", label, "Keep these display settings")


if __name__ == "__main__":
    unittest.main()
