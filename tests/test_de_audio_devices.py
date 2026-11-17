"""On-demand native RiceSpice audio controls: real server data, no shell strings."""

import json
import subprocess
import unittest
from unittest import mock
from types import SimpleNamespace

from macrice.cli import main
from macrice.de import audio_devices, settings
from macrice.de.creator_contract import describe_creator_api


SINK = "alsa_output.pci-0000_00_1b.0.analog-stereo"
USB = "alsa_output.usb-Device-00.analog-stereo"
SOURCE = "alsa_input.pci-0000_00_1b.0.analog-stereo"


def sample_response(*args):
    if args[0] == "--format=json":
        records = ([{"index": 1, "name": SINK, "description": "Internal Speakers"},
                    {"index": 2, "name": USB, "description": "USB Headset"}]
                   if args[-1] == "sinks" else
                   [{"index": 3, "name": SOURCE, "description": "Internal Microphone"}])
        return json.dumps(records)
    if args[0] == "get-default-sink":
        return SINK + "\n"
    if args[0] == "get-default-source":
        return SOURCE + "\n"
    return ""


class AudioDeviceTests(unittest.TestCase):
    def test_inventory_uses_real_names_without_claiming_control(self):
        with mock.patch("macrice.de.audio_devices._run", side_effect=sample_response) as run:
            result = audio_devices.inspect()
        self.assertTrue(result["read_only"])
        self.assertFalse(result["mutates_active_desktop"])
        self.assertEqual([d["default"] for d in result["outputs"]], [True, False])
        self.assertEqual(result["inputs"][0]["name"], SOURCE)
        self.assertEqual(run.call_count, 4)

    def test_no_recording_devices_is_an_honest_empty_list(self):
        def no_inputs(*args):
            if args == ("--format=json", "list", "sources"):
                return "[]"
            return sample_response(*args)
        with mock.patch("macrice.de.audio_devices._run", side_effect=no_inputs) as run:
            result = audio_devices.inspect()
        self.assertEqual(result["inputs"], [])
        self.assertEqual(len(result["outputs"]), 2)
        self.assertEqual(run.call_count, 3)  # No fabricated default microphone.

    def test_switch_one_validated_sink_and_verify_actual_default(self):
        calls = []
        def changing(*args):
            calls.append(args)
            if args[0] == "get-default-sink" and calls.count(("get-default-sink",)) == 2:
                return USB
            return sample_response(*args)
        with mock.patch("macrice.de.audio_devices._run", side_effect=changing):
            result = audio_devices.set_default("sink", USB, expected_current=SINK)
        self.assertTrue(result["changed"])
        self.assertEqual(result["previous"], SINK)
        self.assertEqual(result["current"], USB)
        self.assertIn(("set-default-sink", USB), calls)

    def test_noop_does_not_mutate_and_conflict_fails_before_switch(self):
        with mock.patch("macrice.de.audio_devices._run", side_effect=sample_response) as run:
            result = audio_devices.set_default("sink", SINK)
            self.assertFalse(result["changed"])
            with self.assertRaises(audio_devices.AudioDeviceError) as ctx:
                audio_devices.set_default("sink", USB, expected_current=USB)
        self.assertEqual(ctx.exception.code, "audio_selection_conflict")
        self.assertTrue(all("set-default" not in call.args[0] for call in run.call_args_list))

    def test_reject_missing_or_injection_like_names_without_running_commands(self):
        for candidate in ("; rm -rf /", "--help", "../../run", "", "a" * 161, 1, None):
            with self.subTest(candidate=candidate):
                with mock.patch("macrice.de.audio_devices._run") as run:
                    with self.assertRaises(audio_devices.AudioDeviceError):
                        audio_devices.set_default("sink", candidate)
                    run.assert_not_called()
        with mock.patch("macrice.de.audio_devices._run", side_effect=sample_response):
            with self.assertRaises(audio_devices.AudioDeviceError) as ctx:
                audio_devices.set_default("sink", "missing-output")
        self.assertEqual(ctx.exception.code, "audio_device_missing")

    def test_malformed_oversized_duplicate_and_truncated_inventory_fail_closed(self):
        malformed = ("{}", "not json", json.dumps([{"name": SINK, "index": True}]),
                     json.dumps([{"index": 1, "name": SINK},
                                 {"index": 2, "name": SINK}]),
                     json.dumps([{"index": 1, "name": SINK},
                                 {"index": 1, "name": USB}]),
                     json.dumps([{"index": i, "name": f"sink{i}"}
                                 for i in range(33)]))
        for value in malformed:
            with self.subTest(value=value[:35]):
                with self.assertRaises(audio_devices.AudioDeviceError):
                    audio_devices._devices("sink", value)

    def test_failed_verification_reports_possible_active_mutation(self):
        with mock.patch("macrice.de.audio_devices._run", side_effect=sample_response):
            with self.assertRaises(audio_devices.AudioDeviceError) as ctx:
                audio_devices.set_default("sink", USB)
        self.assertTrue(ctx.exception.may_have_changed)
        self.assertEqual(ctx.exception.code, "audio_verification_failed")
        self.assertTrue(audio_devices.invalid(ctx.exception)["may_have_changed"])

    def test_subprocess_is_bounded_and_never_runs_a_shell(self):
        def fake_run(args, **options):
            self.assertEqual(args, ["/usr/bin/pactl", "get-default-sink"])
            self.assertEqual(options["timeout"], 4)
            self.assertTrue(options["capture_output"])
            self.assertFalse(options["check"])
            return subprocess.CompletedProcess(args, 0, SINK.encode() + b"\n", b"")
        with mock.patch("macrice.de.audio_devices.shutil.which", return_value="/usr/bin/pactl"), \
             mock.patch("macrice.de.audio_devices.subprocess.run", side_effect=fake_run):
            self.assertEqual(audio_devices._run("get-default-sink"), SINK + "\n")

    def test_cli_and_creator_contract_declare_real_mutation(self):
        with mock.patch("macrice.de.audio_devices._run", side_effect=sample_response), \
             mock.patch("builtins.print") as printed:
            self.assertEqual(main(["de", "audio-devices", "--json"]), 0)
            self.assertTrue(json.loads(printed.call_args.args[0])["read_only"])
            self.assertEqual(main(["de", "audio-default", "--device-kind", "sink",
                                   "--device-name", SINK, "--json"]), 0)
            self.assertFalse(json.loads(printed.call_args.args[0])["changed"])
            self.assertEqual(main(["de", "audio-default", "--json"]), 1)
            self.assertEqual(main(["de", "notifications", "--device-kind", "sink", "--json"]), 1)
        contract = describe_creator_api()
        row = next(item for item in contract["commands"] if item["command"] == "audio-default")
        self.assertTrue(row["mutates_active_session"])

    def test_application_stream_routing_volume_and_mute_are_verified(self):
        current = {"index": 42, "sink": 1, "mute": False, "client": 17,
                   "volume": {"front-left": {"value": 32768},
                              "front-right": {"value": 32768}},
                   "properties": {"application.name": "Web browser"}}
        commands = []

        def simulate(*args):
            commands.append(args)
            if args == ("--format=json", "list", "sink-inputs"):
                return json.dumps([current])
            if args == ("move-sink-input", "42", USB):
                current["sink"] = 2
                return ""
            if args == ("set-sink-input-volume", "42", "70%"):
                current["volume"] = {"front-left": {"value": 45875}}
                return ""
            if args == ("set-sink-input-mute", "42", "1"):
                current["mute"] = True
                return ""
            return sample_response(*args)

        with mock.patch.object(audio_devices, "_run", side_effect=simulate):
            before = audio_devices.playback_streams()
            self.assertEqual(before["streams"][0]["volume"], 50)
            self.assertEqual(before["streams"][0]["label"], "Web browser")
            self.assertEqual(before["streams"][0]["client"], 17)
            self.assertEqual(audio_devices.set_stream_output(
                42, USB, expected_sink=1, expected_client=17)["sink"], 2)
            self.assertEqual(audio_devices.set_stream_volume(
                42, 70, expected=50, expected_client=17)["volume"], 70)
            self.assertTrue(audio_devices.set_stream_mute(
                42, True, expected=False, expected_client=17)["mute"])
            with self.assertRaisesRegex(audio_devices.AudioDeviceError, "changed"):
                audio_devices.set_stream_output(42, SINK, expected_sink=1)
        self.assertIn(("move-sink-input", "42", USB), commands)

    def test_recycled_stream_index_never_controls_a_different_audio_client(self):
        current = {"index": 42, "sink": 1, "mute": False, "client": 18,
                   "volume": {"mono": {"value": 65536}},
                   "properties": {"application.name": "Another application"}}
        calls = []

        def simulate(*args):
            calls.append(args)
            if args == ("--format=json", "list", "sink-inputs"):
                return json.dumps([current])
            if args == ("set-sink-input-mute", "42", "1"):
                # A replacement can happen even between mutation and readback.
                current["client"] = 19
                current["mute"] = True
                return ""
            return sample_response(*args)

        with mock.patch.object(audio_devices, "_run", side_effect=simulate):
            for operation in (
                lambda: audio_devices.set_stream_output(
                    42, USB, expected_sink=1, expected_client=17),
                lambda: audio_devices.set_stream_volume(
                    42, 50, expected=100, expected_client=17),
                lambda: audio_devices.set_stream_mute(
                    42, True, expected=False, expected_client=17),
            ):
                with self.assertRaises(audio_devices.AudioDeviceError) as error:
                    operation()
                self.assertEqual(error.exception.code, "audio_stream_changed")
            self.assertFalse(any(call[0].startswith(("move-", "set-sink-input"))
                                 for call in calls))
            # After an initially valid write, a client switch is reported as
            # uncertain rather than falsely claiming control of the new app.
            with self.assertRaises(audio_devices.AudioDeviceError) as error:
                audio_devices.set_stream_mute(
                    42, True, expected=False, expected_client=18)
            self.assertTrue(error.exception.may_have_changed)
            self.assertIn(("set-sink-input-mute", "42", "1"), calls)

    def test_ricespice_readonly_stream_has_no_unsafe_audio_controls(self):
        notes, actions = [], []
        panel = SimpleNamespace()
        panel._text = lambda message, **_kw: notes.append(message)
        panel._state = lambda message: None
        panel._button = lambda label, callback, **_kw: actions.append(label)
        panel._show_content = lambda: None
        panel._background = lambda work, done: done(work())
        panel.Gtk = SimpleNamespace()
        panel.show_page = lambda _page: None
        with mock.patch.object(audio_devices, "inspect", return_value={
                 "outputs": [], "inputs": []}), \
             mock.patch.object(audio_devices, "playback_streams", return_value={
                 "outputs": [], "streams": [{"index": 9, "client": None,
                     "sink": 1, "mute": False, "volume": 100,
                     "label": "Unknown stream"}]}), \
             mock.patch("macrice.de.settings.media.read_media_players", return_value=()):
            settings.RiceSpiceWindow._audio(panel)
        self.assertTrue(any("no verifiable audio client" in note for note in notes))
        self.assertFalse(any("Unknown stream" in label for label in actions))
        self.assertIn("Refresh devices and players", actions)

    def test_ricespice_stream_buttons_pass_displayed_client_identity(self):
        class Combo:
            def __init__(self):
                self.current = None

            def append(self, *_args):
                pass

            def get_accessible(self):
                return self

            def set_name(self, _value):
                pass

            def set_active_id(self, value):
                self.current = value

            def get_active_id(self):
                return self.current

        buttons = {}
        panel = SimpleNamespace()
        panel._text = lambda *_args, **_kw: None
        panel._state = lambda _message: None
        panel._button = lambda label, callback, **_kw: buttons.setdefault(label, callback)
        panel._show_content = lambda: None
        panel._background = lambda work, done: done(work())
        panel.Gtk = SimpleNamespace(ComboBoxText=Combo)
        panel.content = SimpleNamespace(pack_start=lambda *_args: None)
        panel.show_page = lambda _page: None
        stream = {"index": 42, "client": 17, "sink": 1, "mute": False,
                  "volume": 50, "label": "Browser"}
        with mock.patch.object(audio_devices, "inspect", return_value={
                 "outputs": [], "inputs": []}), \
             mock.patch.object(audio_devices, "playback_streams", return_value={
                 "outputs": [{"index": 1, "name": SINK,
                              "description": "Internal Speakers"}],
                 "streams": [stream]}), \
             mock.patch("macrice.de.settings.media.read_media_players", return_value=()), \
             mock.patch.object(audio_devices, "set_stream_output", return_value=stream) as move, \
             mock.patch.object(audio_devices, "set_stream_volume", return_value=stream) as volume, \
             mock.patch.object(audio_devices, "set_stream_mute", return_value=stream) as mute:
            settings.RiceSpiceWindow._audio(panel)
            buttons["Move Browser to selected output"]()
            buttons["Set Browser volume"]()
            buttons["Mute Browser"]()
        move.assert_called_once_with(42, SINK, expected_sink=1, expected_client=17)
        volume.assert_called_once_with(42, 50, expected=50, expected_client=17)
        mute.assert_called_once_with(42, True, expected=False, expected_client=17)

    def test_application_streams_reject_malformed_and_unavailable(self):
        valid = {"index": 4, "sink": 1, "mute": False,
                 "volume": {"mono": {"value": 65536}}, "properties": {}}
        for payload in ("{}", "invalid", json.dumps([valid] * 65),
                        json.dumps([{**valid, "index": True}]),
                        json.dumps([valid, valid]),
                        json.dumps([{**valid, "volume": {"mono": {"value": "100%"}}}]),
                        *(json.dumps([{**valid, "client": invalid}])
                          for invalid in (True, -1, 2**32, "17"))):
            with self.subTest(payload=payload[:30]), \
                    self.assertRaises(audio_devices.AudioDeviceError):
                audio_devices._streams(payload)
        with mock.patch.object(audio_devices, "_run") as command:
            for value in (-1, True, "50", 151):
                with self.assertRaises(audio_devices.AudioDeviceError):
                    audio_devices.set_stream_volume(4, value, expected=40)
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
