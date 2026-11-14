"""Offline safeguards for the opt-in, headless-only portal capture smoke."""
import importlib.util
from contextlib import ExitStack
import os
import socket
import struct
import zlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/wayland_portal_capture_smoke.py"
spec = importlib.util.spec_from_file_location("ricebowl_portal_capture", SCRIPT)
portal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portal)


def sample_png(width: int, height: int) -> bytes:
    """Construct a valid PNG fixture without optional image libraries."""
    def chunk(kind, data):
        crc = zlib.crc32(kind + data) & 0xffffffff
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)
    pixels = (b"\x00" + b"\x42\x68\x93\xff" * width) * height
    return (portal.PNG_SIGNATURE
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels))
            + chunk(b"IEND", b""))


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
                (runtime / ".ricebowl-portal-dbus").write_text(
                    env["DBUS_SESSION_BUS_ADDRESS"] + "\n", encoding="utf-8")
                (runtime / ".ricebowl-portal-dbus").chmod(0o600)
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
                marker = runtime / ".ricebowl-portal-ci"
                marker.rename(runtime / "original-marker")
                marker.symlink_to(runtime / "original-marker")
                with self.assertRaisesRegex(RuntimeError, "marker"):
                    portal.require_private_headless_session(env)
                marker.unlink()
                marker.touch()
                alias = runtime.parent / (runtime.name + "-alias")
                alias.symlink_to(runtime)
                try:
                    with self.assertRaisesRegex(RuntimeError, "symlink"):
                        portal.require_private_headless_session({
                            **env, "XDG_RUNTIME_DIR": str(alias),
                            "PIPEWIRE_RUNTIME_DIR": str(alias)})
                finally:
                    alias.unlink()
                dbus_marker = runtime / ".ricebowl-portal-dbus"
                dbus_marker.write_text("unix:path=/run/user/1000/bus\\n",
                                       encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "D-Bus identity"):
                    portal.require_private_headless_session(env)
                dbus_marker.write_text(
                    env["DBUS_SESSION_BUS_ADDRESS"] + "\n", encoding="utf-8")
                runtime.chmod(0o755)
                with self.assertRaisesRegex(RuntimeError, "0700"):
                    portal.require_private_headless_session(env)

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
            data = sample_png(2, 2)
            image.write_bytes(data)
            self.assertEqual(portal.verify_png(image.as_uri()), (2, 2, len(data)))
            image.write_bytes(b"not PNG")
            with self.assertRaisesRegex(ValueError, "PNG"):
                portal.verify_png(image.as_uri())

    def test_rejects_symlink_and_invalid_dimensions(self):
        with tempfile.TemporaryDirectory() as path:
            image = Path(path) / "image.png"
            image.write_bytes(sample_png(0, 1))
            with self.assertRaisesRegex(ValueError, "dimensions"):
                portal.verify_png(image.as_uri())
            link = Path(path) / "symlink.png"
            link.symlink_to(image)
            with self.assertRaises(OSError):
                portal.verify_png(link.as_uri())

    def test_rejects_bad_crc_and_truncated_png(self):
        with tempfile.TemporaryDirectory() as path:
            image = Path(path) / "frame.png"
            original = sample_png(1, 1)
            broken = bytearray(original)
            broken[32] ^= 1
            image.write_bytes(broken)
            with self.assertRaisesRegex(ValueError, "CRC"):
                portal.verify_png(image.as_uri())
            for data in (original[:-8], original[:33]):
                image.write_bytes(data)
                with self.assertRaisesRegex(ValueError, "PNG"):
                    portal.verify_png(image.as_uri())


class ScreenCastCapabilityTests(unittest.TestCase):
    def test_strict_renderer_and_pixman_fallback_never_mix(self):
        self.assertFalse(portal.strict_ci_mode({}))
        self.assertTrue(portal.strict_ci_mode({
            "RICEBOWL_PORTAL_STRICT_CI": "1", "WLR_RENDERER": "gles2"}))
        for env in ({"RICEBOWL_PORTAL_STRICT_CI": "1", "WLR_RENDERER": "pixman"},
                    {"RICEBOWL_PORTAL_STRICT_CI": "invalid"}):
            with self.assertRaises(RuntimeError):
                portal.strict_ci_mode(env)

    def test_stream_nodes_must_be_unique_bounded_unsigned_and_well_formed(self):
        self.assertEqual(portal.stream_nodes([(12, {}), (55, {"size": (2, 2)})]),
                         (12, 55))
        for invalid in (None, [], [(0, {})], [(True, {})], [(-1, {})],
                        [(4294967296, {})], [(3, None)], [(1, {}), (1, {})],
                        [(2, 3, {})], "3", [(i, {}) for i in range(17)]):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                portal.stream_nodes(invalid)

    def test_fd_lifetime_and_frame_failure_never_claim_success(self):
        with ExitStack() as stack:
            left, right = socket.socketpair()
            stack.enter_context(left)
            stack.enter_context(right)
            fd = os.dup(left.fileno())
            try:
                with patch.object(portal.subprocess, "run", return_value=type(
                    "Result", (), {"returncode": 1, "stdout": "",
                                   "stderr": "no sample"})()) as run:
                    with self.assertRaisesRegex(RuntimeError, "no sample"):
                        portal.verify_delivered_frame(fd, 12)
                    self.assertEqual(run.call_args.kwargs["pass_fds"], (fd,))
                    self.assertEqual(run.call_args.kwargs["timeout"], 18)
                with patch.object(portal.subprocess, "run", return_value=type(
                    "Result", (), {"returncode": 0,
                                   "stdout": "PORTAL_FRAME_OK: node=12 bytes=4096",
                                   "stderr": ""})()):
                    self.assertIn("PORTAL_FRAME_OK:", portal.verify_delivered_frame(fd, 12))
                self.assertTrue(os.fstat(fd).st_mode)
            finally:
                os.close(fd)
            self.assertGreaterEqual(right.fileno(), 0)

    def test_timeout_and_cancel_statuses_are_machine_readable(self):
        self.assertEqual(portal.classify_failure(TimeoutError("late")), "request_timeout")
        self.assertEqual(portal.classify_failure(portal.PortalRejected("Start", 1)),
                         "request_cancelled")
        self.assertEqual(portal.classify_failure(portal.PortalRejected("Start", 2)),
                         "session_start_failed")
        self.assertEqual(portal.classify_failure(portal.PortalRejected("SelectSources", 2)),
                         "request_denied_or_failed")
        self.assertEqual(portal.classify_failure(RuntimeError("Missing Unix FD")),
                         "fd_missing_or_invalid")
        self.assertEqual(portal.classify_failure(RuntimeError("Permission denied")),
                         "permission_denied")
        self.assertEqual(portal.classify_failure(RuntimeError("No DRM render node")),
                         "renderer_unavailable")

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
