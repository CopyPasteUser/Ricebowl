"""Offline safeguards for the opt-in, headless-only portal capture smoke."""
import importlib.util
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/wayland_portal_capture_smoke.py"
spec = importlib.util.spec_from_file_location("ricebowl_portal_capture", SCRIPT)
portal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portal)


class CaptureGuardTests(unittest.TestCase):
    def test_requires_private_headless_runtime_and_compositor_socket(self):
        with tempfile.TemporaryDirectory() as path:
            runtime = Path(path)
            runtime.chmod(0o700)
            (runtime / ".ricebowl-portal-ci").touch()
            # This local sandbox cannot create Unix sockets. Mock only the
            # filesystem socket check; GitHub CI exercises a real compositor.
            with patch.object(Path, "is_socket", return_value=True):
                env = {
                    "RICEBOWL_PORTAL_CAPTURE_CI": "1",
                    "RICEBOWL_DE_NESTED": "1",
                    "WLR_BACKENDS": "headless",
                    "XDG_SESSION_TYPE": "wayland",
                    "XDG_RUNTIME_DIR": path,
                    "PIPEWIRE_RUNTIME_DIR": path,
                    "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + path + "/bus",
                    "WAYLAND_DISPLAY": "wayland-1",
                }
                self.assertEqual(portal.require_private_headless_session(env), runtime)
                for key, bad in (
                    ("RICEBOWL_PORTAL_CAPTURE_CI", "0"),
                    ("WLR_BACKENDS", "wayland"),
                    ("XDG_RUNTIME_DIR", "/tmp"),
                    ("PIPEWIRE_RUNTIME_DIR", "/run/user/1000"),
                    ("WAYLAND_DISPLAY", "/run/user/1000/wayland-1"),
                    ("DBUS_SESSION_BUS_ADDRESS", ""),
                ):
                    modified = {**env, key: bad}
                    with self.subTest(key=key, bad=bad):
                        with self.assertRaises(RuntimeError):
                            portal.require_private_headless_session(modified)
                (runtime / ".ricebowl-portal-ci").unlink()
                with self.assertRaisesRegex(RuntimeError, "marker"):
                    portal.require_private_headless_session(env)
                (runtime / ".ricebowl-portal-ci").touch()
                runtime.chmod(0o755)
                with self.assertRaisesRegex(RuntimeError, "0700"):
                    portal.require_private_headless_session(env)
                runtime.chmod(0o700)
                marker = runtime / ".ricebowl-portal-ci"
                marker.unlink()
                original = runtime / "original-marker"
                original.touch()
                marker.symlink_to(original)
                with self.assertRaisesRegex(RuntimeError, "marker"):
                    portal.require_private_headless_session(env)
                marker.unlink()
                marker.touch()
                alias = runtime.parent / (runtime.name + "-alias")
                alias.symlink_to(runtime, target_is_directory=True)
                try:
                    with self.assertRaisesRegex(RuntimeError, "symlink"):
                        portal.require_private_headless_session({
                            **env, "XDG_RUNTIME_DIR": str(alias),
                            "PIPEWIRE_RUNTIME_DIR": str(alias)})
                finally:
                    alias.unlink()

    def test_rejects_capture_outside_private_session(self):
        with self.assertRaises(RuntimeError):
            portal.require_private_headless_session(dict(os.environ))


class ScreenshotValidationTests(unittest.TestCase):
    def test_accepts_only_local_file_uris(self):
        self.assertEqual(portal.screenshot_file("file:///tmp/screen%20test.png"),
                         Path("/tmp/screen test.png"))
        for bad in ("https://host/screen.png", "file://otherhost/tmp/s.png",
                    "file:relative.png", "file:///tmp/s.png?foo=bar", ""):
            with self.subTest(uri=bad), self.assertRaises(ValueError):
                portal.screenshot_file(bad)

    def test_png_header_dimensions_and_truncated_data(self):
        with tempfile.TemporaryDirectory() as path:
            image = Path(path) / "screenshot.png"
            image.write_bytes(portal.PNG_SIGNATURE + b"\x00\x00\x00\x0dIHDR"
                              + struct.pack(">II", 1920, 1080) + b"\x00" * 9)
            self.assertEqual(portal.verify_png(image.as_uri()), (1920, 1080, 33))
            image.write_bytes(b"not PNG")
            with self.assertRaisesRegex(ValueError, "PNG"):
                portal.verify_png(image.as_uri())

    def test_rejects_symlink_and_invalid_dimensions(self):
        with tempfile.TemporaryDirectory() as path:
            image = Path(path) / "image.png"
            image.write_bytes(portal.PNG_SIGNATURE + b"\x00\x00\x00\x0dIHDR"
                              + struct.pack(">II", 0, 42) + b"\x00" * 9)
            with self.assertRaisesRegex(ValueError, "dimensions"):
                portal.verify_png(image.as_uri())
            link = Path(path) / "symlink.png"
            link.symlink_to(image)
            with self.assertRaises(OSError):
                portal.verify_png(link.as_uri())


class ScreenCastCapabilityTests(unittest.TestCase):
    def test_strict_mode_never_accepts_pixman_or_invalid_flags(self):
        self.assertFalse(portal.strict_ci_mode({}))
        self.assertTrue(portal.strict_ci_mode({
            "RICEBOWL_PORTAL_STRICT_CI": "1", "WLR_RENDERER": "gles2"}))
        for env in (
            {"RICEBOWL_PORTAL_STRICT_CI": "1", "WLR_RENDERER": "pixman"},
            {"RICEBOWL_PORTAL_STRICT_CI": "1"},
            {"RICEBOWL_PORTAL_STRICT_CI": "yes", "WLR_RENDERER": "gles2"},
        ):
            with self.subTest(env=env), self.assertRaises(RuntimeError):
                portal.strict_ci_mode(env)
        self.assertFalse(portal.unsupported_pixman_start(
            portal.PortalRejected("Start", 2), {
                "RICEBOWL_PORTAL_CAPTURE_CI": "1",
                "RICEBOWL_PORTAL_STRICT_CI": "1",
                "WLR_BACKENDS": "headless",
                "WLR_RENDERER": "gles2",
            }))

    def test_start_requires_real_distinct_bounded_stream_nodes(self):
        self.assertEqual(portal.stream_nodes([(42, {}), (73, {"source_type": 1})]),
                         (42, 73))
        for bad in (None, [], [()], [(True, {})], [(0, {})],
                    [(-1, {})], [(4294967296, {})], [(3, None)],
                    [(4, {})] * 2, [(5, {}, "extra")],
                    "bad", [(i, {}) for i in range(17)]):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                portal.stream_nodes(bad)

    def test_script_restricts_renderer_and_has_separate_strict_contract(self):
        source = (SCRIPT.parent / "smoke_wayland_portals.sh").read_text(encoding="utf-8")
        self.assertIn('case "$renderer" in', source)
        self.assertIn('case "$strict" in', source)
        self.assertIn('export WLR_RENDERER="$renderer"', source)
        self.assertIn('export RICEBOWL_PORTAL_STRICT_CI="$strict"', source)

    def test_only_ci_pixman_headless_start_failure_is_non_blocking(self):
        env = {"RICEBOWL_PORTAL_CAPTURE_CI": "1", "WLR_BACKENDS": "headless",
               "WLR_RENDERER": "pixman"}
        self.assertTrue(portal.unsupported_pixman_start(
            portal.PortalRejected("Start", 2), env))
        self.assertFalse(portal.unsupported_pixman_start(
            portal.PortalRejected("Start", 1), env))
        for key, value in (("RICEBOWL_PORTAL_CAPTURE_CI", "0"),
                           ("WLR_BACKENDS", "wayland"),
                           ("WLR_RENDERER", "gles2")):
            with self.subTest(key=key):
                self.assertFalse(portal.unsupported_pixman_start(
                    portal.PortalRejected("Start", 2), {**env, key: value}))


@unittest.skipUnless(importlib.util.find_spec("gi"), "PyGObject not available")
class RequestProtocolTests(unittest.TestCase):
    def test_response_signal_receives_six_gio_callback_arguments(self):
        from gi.repository import GLib

        class FakeConnection:
            def get_unique_name(self):
                return ":1.25"

            def signal_subscribe(self, _dest, _iface, _signal, path,
                                 _arg0, _flags, callback):
                self.path = path
                self.callback = callback
                return 5

            def call_sync(self, *_args):
                self.callback(self, ":1.4", self.path, portal.REQUEST,
                              "Response", GLib.Variant("(ua{sv})", (
                                  0, {"uri": GLib.Variant("s", "file:///tmp/test.png")}
                              )))
                return GLib.Variant("(o)", (self.path,))

            def signal_unsubscribe(self, subscription):
                self.unsubscribed = subscription

        fake = FakeConnection()
        response = portal.request(fake, portal.SCREENSHOT, "Screenshot",
                                  "(sa{sv})", ("",))
        self.assertEqual(response["uri"], "file:///tmp/test.png")
        self.assertEqual(fake.unsubscribed, 5)


if __name__ == "__main__":
    unittest.main()
