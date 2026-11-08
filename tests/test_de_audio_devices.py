"""On-demand native RiceSpice audio controls: real server data, no shell strings."""

import json
import subprocess
import unittest
from unittest import mock

from macrice.cli import main
from macrice.de import audio_devices
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
        current = {"index": 42, "sink": 1, "mute": False,
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
            self.assertEqual(audio_devices.set_stream_output(42, USB, expected_sink=1)["sink"], 2)
            self.assertEqual(audio_devices.set_stream_volume(42, 70, expected=50)["volume"], 70)
            self.assertTrue(audio_devices.set_stream_mute(42, True, expected=False)["mute"])
            with self.assertRaisesRegex(audio_devices.AudioDeviceError, "changed"):
                audio_devices.set_stream_output(42, SINK, expected_sink=1)
        self.assertIn(("move-sink-input", "42", USB), commands)

    def test_application_streams_reject_malformed_and_unavailable(self):
        valid = {"index": 4, "sink": 1, "mute": False,
                 "volume": {"mono": {"value": 65536}}, "properties": {}}
        for payload in ("{}", "invalid", json.dumps([valid] * 65),
                        json.dumps([{**valid, "index": True}]),
                        json.dumps([valid, valid]),
                        json.dumps([{**valid, "volume": {"mono": {"value": "100%"}}}])):
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
