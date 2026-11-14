"""Deterministic real-source-only policy-link guard tests."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ci_portal_pipewire_link import verified_video_ports


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


if __name__ == "__main__":
    unittest.main()
