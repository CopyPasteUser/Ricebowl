"""SG2: malformed pactl JSON must never authorize another audio client/device.

These tests use a synthetic PulseAudio/PipeWire response. No pactl executable
or sound server is contacted, and no active system setting is changed.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from macrice.de import audio_devices


SINK = "alsa_output.demo"
OTHER = "alsa_output.other"


def stream() -> dict:
    return {
        "index": 42, "sink": 1, "client": 17, "mute": False,
        "volume": {"mono": {"value": 65536}},
        "properties": {"application.name": "Browser"},
    }


class AudioJSONIdentityTests(unittest.TestCase):
    def test_duplicate_device_identity_fails_closed_at_each_key(self):
        cases = (
            '[{"index":1,"name":"alsa_output.demo","name":"alsa_output.other"}]',
            '[{"index":1,"index":2,"name":"alsa_output.demo"}]',
            '[{"index":1,"name":"alsa_output.demo","description":"A","description":"B"}]',
        )
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(audio_devices.AudioDeviceError) as ctx:
                audio_devices._devices("sink", payload)
            self.assertEqual(ctx.exception.code, "audio_response_invalid")
        self.assertEqual(audio_devices._devices(
            "sink", json.dumps([{"index": 1, "name": SINK}])),
            [{"index": 1, "name": SINK, "description": ""}])

    def test_duplicate_stream_client_route_mute_and_nested_volume_rejected(self):
        original = json.dumps([stream()])
        replacements = (
            ('"client": 17', '"client": 17, "client": 18'),
            ('"sink": 1', '"sink": 1, "sink": 2'),
            ('"index": 42', '"index": 42, "index": 43'),
            ('"mute": false', '"mute": false, "mute": true'),
            ('"value": 65536', '"value": 65536, "value": 0'),
            ('"application.name": "Browser"',
             '"application.name": "Browser", "application.name": "Other"'),
        )
        for marker, replacement in replacements:
            with self.subTest(marker=marker):
                self.assertIn(marker, original)
                with self.assertRaises(audio_devices.AudioDeviceError):
                    audio_devices._streams(original.replace(marker, replacement))
        self.assertEqual(audio_devices._streams(original)[0]["client"], 17)

    def test_ambiguous_default_device_blocks_write_before_any_pactl_mutation(self):
        commands = []

        def fake_run(*args):
            commands.append(args)
            if args == ("--format=json", "list", "sinks"):
                return '[{"index":1,"name":"alsa_output.demo","name":"alsa_output.other"}]'
            raise AssertionError(f"Unexpected pactl invocation: {args!r}")

        with mock.patch.object(audio_devices, "_run", side_effect=fake_run):
            with self.assertRaises(audio_devices.AudioDeviceError):
                audio_devices.set_default("sink", OTHER, expected_current=SINK)
        self.assertEqual(commands, [("--format=json", "list", "sinks")])

    def test_ambiguous_playback_client_blocks_mutation_before_pactl_write(self):
        bad_stream = json.dumps([stream()]).replace(
            '"client": 17', '"client": 17, "client": 18')
        commands = []

        def fake_run(*args):
            commands.append(args)
            if args == ("--format=json", "list", "sinks"):
                return json.dumps([{"index": 1, "name": SINK}])
            if args == ("get-default-sink",):
                return SINK
            if args == ("--format=json", "list", "sink-inputs"):
                return bad_stream
            raise AssertionError(f"Unexpected pactl invocation: {args!r}")

        with mock.patch.object(audio_devices, "_run", side_effect=fake_run):
            with self.assertRaises(audio_devices.AudioDeviceError):
                audio_devices.set_stream_mute(42, True, expected=False, expected_client=17)
        self.assertEqual(commands, [
            ("--format=json", "list", "sinks"),
            ("get-default-sink",),
            ("--format=json", "list", "sink-inputs"),
        ])


    def test_default_write_timeout_is_indeterminate_and_never_replayed(self):
        calls = []

        def fake_run(*args):
            calls.append(args)
            if args == ("--format=json", "list", "sinks"):
                return json.dumps([{"index": 1, "name": SINK},
                                   {"index": 2, "name": OTHER}])
            if args == ("get-default-sink",):
                return SINK
            if args == ("set-default-sink", OTHER):
                raise audio_devices.AudioDeviceError("Provider reply lost")
            raise AssertionError(f"Unexpected pactl invocation: {args!r}")

        with mock.patch.object(audio_devices, "_run", side_effect=fake_run):
            with self.assertRaises(audio_devices.AudioDeviceError) as caught:
                audio_devices.set_default("sink", OTHER, expected_current=SINK)
        self.assertTrue(caught.exception.may_have_changed)
        self.assertTrue(audio_devices.invalid(caught.exception)["may_have_changed"])
        self.assertEqual(calls.count(("set-default-sink", OTHER)), 1)

    def test_stream_write_timeout_does_not_repeat_or_claim_unchanged(self):
        calls = []

        def fake_run(*args):
            calls.append(args)
            if args == ("--format=json", "list", "sinks"):
                return json.dumps([{"index": 1, "name": SINK}])
            if args == ("get-default-sink",):
                return SINK
            if args == ("--format=json", "list", "sink-inputs"):
                return json.dumps([stream()])
            if args == ("set-sink-input-mute", "42", "1"):
                raise audio_devices.AudioDeviceError("Provider disconnected")
            raise AssertionError(f"Unexpected pactl invocation: {args!r}")

        with mock.patch.object(audio_devices, "_run", side_effect=fake_run):
            with self.assertRaises(audio_devices.AudioDeviceError) as caught:
                audio_devices.set_stream_mute(42, True, expected=False,
                                              expected_client=17)
        self.assertTrue(caught.exception.may_have_changed)
        self.assertEqual(calls.count(("set-sink-input-mute", "42", "1")), 1)


if __name__ == "__main__":
    unittest.main()
