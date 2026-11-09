"""Bounded, non-destructive tests for the optional Wayland suite utilities."""

import base64
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from macrice.cli import main as cli
from macrice.de import riceclip, riceshot


PNG = b"\x89PNG\r\n\x1a\n" + b"some-valid-capture-test-pixels"


class RiceClipTests(unittest.TestCase):
    def test_bounded_deduplicated_private_history_with_pins(self):
        history = riceclip.History()
        self.assertTrue(history.add(riceclip.MIMES[0], "Grüße 💠".encode()))
        self.assertTrue(history.add(riceclip.MIMES[0], "Grüße 💠".encode()))
        self.assertEqual(len(history.items), 1)
        first = history.items[0]
        self.assertEqual(first.preview, "Grüße 💠")
        self.assertFalse(history.add(riceclip.MIMES[0], b"a" * (riceclip.MAX_TEXT + 1)))
        self.assertFalse(history.add(riceclip.MIMES[0], b"bad\x00value"))
        self.assertFalse(history.add("application/octet-stream", b"secret"))
        history.paused = True
        self.assertFalse(history.add(riceclip.MIMES[0], b"private"))
        history.paused = False
        riceclip._handle(history, {"op": "pin", "id": first.id})
        for index in range(riceclip.MAX_ITEMS + 10):
            history.add(riceclip.MIMES[0], f"item-{index}".encode())
        self.assertLessEqual(len(history.items), riceclip.MAX_ITEMS)
        self.assertTrue(history.get(first.id).pinned)
        self.assertNotIn("private", str(history.list()))
        riceclip._handle(history, {"op": "clear"})
        self.assertFalse(history.items)

    def test_image_uri_unicode_and_copy_back(self):
        history = riceclip.History()
        self.assertTrue(history.add("image/png", PNG))
        self.assertTrue(history.add("text/uri-list", b"file:///tmp/%C3%A4\r\n"))
        item = history.items[0]
        with mock.patch("macrice.de.riceclip.shutil.which", return_value="/usr/bin/wl-copy"), \
             mock.patch("macrice.de.riceclip.subprocess.run") as run:
            self.assertEqual(riceclip._handle(history, {"op": "paste", "id": item.id}), {"ok": True})
        self.assertEqual(run.call_args.args[0], ["/usr/bin/wl-copy", "--type", "text/uri-list"])
        self.assertEqual(run.call_args.kwargs["input"], item.data)
        self.assertFalse(history.add("image/png", b"not png"))

    def test_private_socket_api_is_ephemeral_and_stops(self):
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.close()
        except PermissionError:
            self.skipTest("AF_UNIX socket creation is blocked in this test environment")
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o700)

            class FakeWatcher:
                def poll(self):
                    return None

                def terminate(self):
                    pass

                def wait(self, timeout=None):
                    return 0

            errors = []

            def serve():
                try:
                    riceclip._serve()
                except Exception as exc:
                    errors.append(exc)

            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": directory,
                                              "WAYLAND_DISPLAY": "test"}), \
                 mock.patch("macrice.de.riceclip.shutil.which", return_value="/usr/bin/wl-paste"), \
                 mock.patch("macrice.de.riceclip.subprocess.Popen", return_value=FakeWatcher()):
                thread = threading.Thread(target=serve)
                thread.start()
                try:
                    for _ in range(100):
                        if (Path(directory) / "ricebowl/riceclip.sock").exists():
                            break
                        threading.Event().wait(0.01)
                    payload = base64.b64encode(b"hello").decode()
                    self.assertTrue(riceclip._request("ingest", mime=riceclip.MIMES[0],
                                                     data=payload)["added"])
                    self.assertEqual(riceclip._request("list")["items"][0]["preview"], "hello")
                    riceclip._request("stop")
                finally:
                    thread.join(timeout=5)
                self.assertFalse(errors, errors)
                self.assertFalse(thread.is_alive())
                self.assertFalse((Path(directory) / "ricebowl/riceclip.sock").exists())

    def test_cli_recognizes_optional_tools_without_starting_services(self):
        with mock.patch("macrice.de.riceclip.run", return_value=0) as run:
            self.assertEqual(cli(["riceclip", "status"]), 0)
            run.assert_called_once_with("status", identifier=None, mime=None)
        with mock.patch("macrice.de.riceshot.shoot", return_value=None) as shoot:
            with mock.patch("builtins.print"):
                self.assertEqual(cli(["riceshot", "--mode", "monitor", "--clipboard"]), 0)
            self.assertEqual(shoot.call_args.kwargs["mode"], "monitor")

    def test_desktop_screenshot_reports_outcome_without_requiring_notification_service(self):
        with mock.patch("macrice.de.riceshot.shoot", return_value=None), \
             mock.patch("macrice.cli.subprocess.run", side_effect=FileNotFoundError), \
             mock.patch("builtins.print"):
            self.assertEqual(cli(["riceshot", "--mode", "full", "--notify"]), 0)
        with mock.patch("macrice.de.riceshot.shoot", side_effect=riceshot.ShotError("cancelled")), \
             mock.patch("macrice.cli.subprocess.run") as notify, \
             mock.patch("sys.stderr"):
            self.assertEqual(cli(["riceshot", "--notify"]), 1)
            notify.assert_called_once()


class RiceShotTests(unittest.TestCase):
    def test_region_selection_cancellation_does_not_capture(self):
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "test"}), \
             mock.patch("macrice.de.riceshot.shutil.which", return_value="/usr/bin/slurp"), \
             mock.patch("macrice.de.riceshot.subprocess.run") as selection, \
             mock.patch("macrice.de.riceshot.capture") as capture:
            selection.return_value.returncode = 1
            selection.return_value.stdout = ""
            with self.assertRaisesRegex(riceshot.ShotError, "cancelled"):
                riceshot.shoot(mode="region", clipboard=True)
            capture.assert_not_called()

    def test_capture_to_private_new_file_and_clipboard(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "screen.png"

            def fake_capture(path, *, geometry=None):
                path.write_bytes(PNG)

            with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "test"}), \
                 mock.patch("macrice.de.riceshot.shutil.which", return_value="/usr/bin/wl-copy"), \
                 mock.patch("macrice.de.riceshot.capture", side_effect=fake_capture) as capture, \
                 mock.patch("macrice.de.riceshot.subprocess.run") as run:
                self.assertEqual(riceshot.shoot(mode="full", destination=target,
                                                clipboard=True), target)
            self.assertEqual(target.read_bytes(), PNG)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertIsNone(capture.call_args.kwargs["geometry"])
            self.assertEqual(run.call_args.kwargs["input"], PNG)
            with self.assertRaisesRegex(riceshot.ShotError, "no overwrite"):
                riceshot.shoot(mode="full", destination=target)
            alias = Path(directory) / "alias.png"
            alias.symlink_to(target)
            with self.assertRaisesRegex(riceshot.ShotError, "no overwrite"):
                riceshot.shoot(mode="full", destination=alias)

    def test_annotation_requires_explicit_optional_tool(self):
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "test"}), \
             mock.patch("macrice.de.riceshot.shutil.which", return_value=None):
            with self.assertRaisesRegex(riceshot.ShotError, "swappy"):
                riceshot.shoot(mode="full", annotate=True, clipboard=True)

    def test_geometry_does_not_accept_arbitrary_grim_arguments(self):
        from macrice.de.capture import CaptureError, capture
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "test"}), \
             mock.patch("macrice.de.capture.shutil.which", return_value="/usr/bin/grim"):
            for geometry in ("--help", "1,2 0x10", "0,0 99999x10", "0,0 5000x5000"):
                with self.subTest(geometry=geometry), self.assertRaises(CaptureError):
                    capture(Path(folder) / "s.png", geometry=geometry)


if __name__ == "__main__":
    unittest.main()
