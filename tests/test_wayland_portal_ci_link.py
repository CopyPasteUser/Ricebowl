"""Deterministic real-source-only policy-link guard tests."""
import os
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ci_portal_pipewire_link import checked_runtime, verified_video_ports


def node(i, name, media):
    return {"id": i, "type": "PipeWire:Interface:Node",
            "info": {"props": {"node.name": name, "media.class": media}}}


def port(i, owner, direction):
    return {"id": i, "type": "PipeWire:Interface:Port",
            "info": {"props": {"node.id": str(owner),
                               "port.direction": direction}}}


class PrivateLinkTests(unittest.TestCase):
    def test_links_only_unique_real_capture_and_named_receiver(self):
        registry = [
            node(40, "xdp-capture-36", "Video/Source"),
            node(43, "ricebowl-ci-consumer", "Stream/Input/Video"),
            node(7, "unrelated-audio", "Audio/Sink"),
            port(41, 40, "out"), port(44, 43, "in"), port(9, 7, "in"),
        ]
        self.assertEqual(verified_video_ports(registry), (41, 44))
        for bad in (
            registry + [port(47, 43, "in")],
            registry + [node(50, "xdp-capture-22", "Video/Source")],
            [n for n in registry if n.get("id") != 43],
            [n for n in registry if n.get("id") != 44],
        ):
            self.assertIsNone(verified_video_ports(bad))
        with self.assertRaises(ValueError):
            verified_video_ports({})


class DisposableGuardTests(unittest.TestCase):
    """The link guard accepts a hosted or a local-CI disposable runner only."""

    STRICT = {"RICEBOWL_PORTAL_CAPTURE_CI": "1", "RICEBOWL_PORTAL_STRICT_CI": "1",
              "RICEBOWL_PORTAL_BACKEND": "generic", "WLR_BACKENDS": "headless",
              "WLR_RENDERER": "pixman"}

    def refused(self, extra):
        env = {**self.STRICT, **extra}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "outside strict disposable CI"):
                checked_runtime()

    def test_refuses_without_a_disposable_runner_marker(self):
        self.refused({})
        self.refused({"GITHUB_ACTIONS": "false"})
        self.refused({"RICEBOWL_LOCAL_CI_DISPOSABLE": "0"})

    def test_strict_environment_is_still_required(self):
        for key in self.STRICT:
            env = {**self.STRICT, "RICEBOWL_LOCAL_CI_DISPOSABLE": "1"}
            env[key] = "wrong"
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(RuntimeError, "outside strict disposable CI"):
                    checked_runtime()

    def test_local_ci_marker_passes_the_environment_gate(self):
        env = {**self.STRICT, "RICEBOWL_LOCAL_CI_DISPOSABLE": "1"}
        with mock.patch.dict(os.environ, env, clear=True):
            # Gets past the environment gate and stops at the missing runtime.
            with self.assertRaisesRegex(RuntimeError, "Invalid private PipeWire runtime"):
                checked_runtime()


if __name__ == "__main__":
    unittest.main()
