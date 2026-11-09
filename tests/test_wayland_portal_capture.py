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


if __name__ == "__main__":
    unittest.main()
