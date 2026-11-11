"""Owner-initiated, bounded real Wayland screenshot Creator contract."""

import hashlib
import json
import os
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from macrice.cli import main as cli
from macrice.de import capture, catalog, creator_contract


def png() -> bytes:
    """Small valid PNG using only the standard library."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    raw = (b"\x00" + b"\x41\x79\xaa" * 16) * 16
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class WaylandCaptureTests(unittest.TestCase):
    def test_discovery_is_explicit_and_truthful(self):
        spec = catalog.describe()["authoring"]["capture"]
        self.assertEqual(spec, creator_contract.describe_capture())
        self.assertTrue(spec["requires_running_wayland_session"])
        self.assertTrue(spec["screenshot_may_contain_private_data"])
        self.assertFalse(spec["creates_nested_session"])
        self.assertEqual(spec["required_options"], ["--output"])

    def test_cli_creates_private_capture_without_modifying_the_session(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "capture.png"
            pixels = png()

            def fake_grim(command, *, stdout, stderr, timeout, check):
                self.assertEqual(command, ["/usr/bin/grim", "-"])
                self.assertEqual(timeout, 30)
                self.assertTrue(check)
                stdout.write(pixels)
                return subprocess.CompletedProcess(command, 0)

            with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-test"}), \
                 mock.patch("macrice.de.capture.shutil.which", return_value="/usr/bin/grim"), \
                 mock.patch("macrice.de.capture.subprocess.run", side_effect=fake_grim) as run, \
                 mock.patch("macrice.de.session.start") as session, \
                 mock.patch("macrice.de.recipes.change_selection") as selection, \
                 mock.patch("builtins.print") as printer:
                self.assertEqual(cli(["de", "capture", "--output", str(destination), "--json"]), 0)
            result = json.loads(printer.call_args.args[0])
            self.assertTrue(result["ok"])
            self.assertEqual(result["creator_contract_version"], 1)
            self.assertEqual(result["capture"]["source"], "current-wayland-compositor")
            self.assertEqual(result["capture"]["sha256"], hashlib.sha256(pixels).hexdigest())
            self.assertEqual((result["capture"]["width"], result["capture"]["height"]), (16, 16))
            self.assertEqual(destination.read_bytes(), pixels)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertFalse(result["capture"]["mutates_active_desktop"])
            self.assertEqual(run.call_count, 1)
            session.assert_not_called()
            selection.assert_not_called()

    def test_refuses_overwrite_and_symlink_even_with_grim_present(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "existing.png"
            dest.write_bytes(b"keep me")
            alias = Path(folder) / "link.png"
            alias.symlink_to(dest)
            with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-test"}), \
                 mock.patch("macrice.de.capture.shutil.which", return_value="/usr/bin/grim"), \
                 mock.patch("macrice.de.capture.subprocess.run") as run:
                for path in (dest, alias):
                    with self.subTest(path=path):
                        with self.assertRaises(capture.CaptureError) as raised:
                            capture.capture(path)
                        self.assertEqual(raised.exception.code, "invalid_capture_request")
                run.assert_not_called()
            self.assertEqual(dest.read_bytes(), b"keep me")

    def test_unavailable_wayland_and_invalid_png_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "secret.png"
            with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": ""}), \
                 mock.patch("builtins.print") as printer:
                self.assertEqual(cli(["de", "capture", "--output", str(destination), "--json"]), 2)
            failure = json.loads(printer.call_args.args[0])
            self.assertEqual(failure["error"]["code"], "capture_unavailable")
            self.assertNotIn(folder, json.dumps(failure))
            self.assertFalse(destination.exists())

            def bad_grim(command, *, stdout, stderr, timeout, check):
                stdout.write(b"not a screenshot")
                return subprocess.CompletedProcess(command, 0)

            with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-test"}), \
                 mock.patch("macrice.de.capture.shutil.which", return_value="/usr/bin/grim"), \
                 mock.patch("macrice.de.capture.subprocess.run", side_effect=bad_grim), \
                 mock.patch("builtins.print") as printer:
                self.assertEqual(cli(["de", "capture", "--output", str(destination), "--json"]), 2)
            failure = json.loads(printer.call_args.args[0])
            self.assertEqual(failure["error"]["code"], "capture_failed")
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(folder).glob(".ricebowl-capture-*")), [])

    def test_truncated_png_and_timed_out_grim_leave_no_partial_files(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "capture.png"

            def interrupted(command, *, stdout, stderr, timeout, check):
                stdout.write(png()[:-12])  # Missing IEND marker.
                return subprocess.CompletedProcess(command, 0)

            def hung(command, *, stdout, stderr, timeout, check):
                raise subprocess.TimeoutExpired(command, timeout)

            for fake in (interrupted, hung):
                with self.subTest(fake=fake.__name__), \
                     mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-test"}), \
                     mock.patch("macrice.de.capture.shutil.which", return_value="/usr/bin/grim"), \
                     mock.patch("macrice.de.capture.subprocess.run", side_effect=fake):
                    with self.assertRaises(capture.CaptureError) as raised:
                        capture.capture(destination)
                    self.assertEqual(raised.exception.code, "capture_failed")
                self.assertFalse(destination.exists())
                self.assertEqual(list(Path(folder).glob(".ricebowl-capture-*")), [])

    def test_capture_arguments_are_separate_from_other_creator_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            for arguments in (
                ["de", "catalog", "--output", str(Path(folder) / "no.png")],
                ["de", "capture", "--recipe", "classic", "--output", str(Path(folder) / "a.png")],
                ["de", "capture", "--nested", "--output", str(Path(folder) / "b.png")],
                ["de", "capture", "--panel", "native", "--output", str(Path(folder) / "c.png")],
            ):
                with self.subTest(arguments=arguments), mock.patch("sys.stderr"):
                    self.assertEqual(cli(arguments), 1)

    def test_riceshot_explicit_full_and_named_output_reuse_private_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            for mode, extra, expected in (
                ("full", [], ["/usr/bin/grim", "-"]),
                ("output", ["--monitor", "HDMI-A-1"],
                 ["/usr/bin/grim", "-o", "HDMI-A-1", "-"]),
            ):
                destination = Path(folder) / f"{mode}.png"

                def fake_grim(command, *, stdout, stderr, timeout, check):
                    self.assertEqual(command, expected)
                    stdout.write(png())
                    return subprocess.CompletedProcess(command, 0)

                with self.subTest(mode=mode), \
                     mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-test"}), \
                     mock.patch("macrice.de.capture.shutil.which", return_value="/usr/bin/grim"), \
                     mock.patch("macrice.de.capture.subprocess.run", side_effect=fake_grim), \
                     mock.patch("builtins.print") as printer:
                    result = cli(["de", "shot", "--shot-mode", mode, *extra,
                                  "--output", str(destination), "--json"])
                self.assertEqual(result, 0)
                report = json.loads(printer.call_args.args[0])
                self.assertEqual(report["riceshot_version"], 1)
                self.assertEqual(report["capture"]["mode"], mode)
                self.assertEqual(destination.read_bytes(), png())
                self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_riceshot_region_selection_passes_validated_slurp_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "region.png"
            commands = []

            def fake_run(command, **kwargs):
                commands.append(command)
                if command[0] == "/usr/bin/slurp":
                    return subprocess.CompletedProcess(command, 0, stdout="-400,12 320x180\n")
                self.assertEqual(command, ["/usr/bin/grim", "-g", "-400,12 320x180", "-"])
                kwargs["stdout"].write(png())
                return subprocess.CompletedProcess(command, 0)

            with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-test"}), \
                 mock.patch("macrice.de.capture.shutil.which",
                            side_effect=lambda name: f"/usr/bin/{name}"), \
                 mock.patch("macrice.de.capture.subprocess.run", side_effect=fake_run):
                result = capture.capture(destination, mode="region")
            self.assertEqual(result["mode"], "region")
            self.assertEqual([command[0] for command in commands],
                             ["/usr/bin/slurp", "/usr/bin/grim"])
            self.assertEqual(destination.read_bytes(), png())

    def test_riceshot_invalid_or_cancelled_selection_never_creates_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "never.png"
            with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-test"}), \
                 mock.patch("macrice.de.capture.shutil.which",
                            side_effect=lambda name: "/usr/bin/grim" if name == "grim" else None), \
                 mock.patch("macrice.de.capture.subprocess.run") as run:
                with self.assertRaisesRegex(capture.CaptureError, "requires slurp"):
                    capture.capture(destination, mode="region")
                run.assert_not_called()
            for invalid in ("-fake", "with spaces", "x" * 81):
                with self.subTest(invalid=invalid), \
                     mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-test"}), \
                     mock.patch("macrice.de.capture.shutil.which",
                                return_value="/usr/bin/grim"), \
                     mock.patch("macrice.de.capture.subprocess.run") as run:
                    with self.assertRaisesRegex(capture.CaptureError, "valid screenshot"):
                        capture.capture(destination, mode="output", monitor=invalid)
                    run.assert_not_called()
            for response in (subprocess.CompletedProcess([], 1, stdout=""),
                             subprocess.CompletedProcess([], 0, stdout="1,2 9000x2")):
                with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-test"}), \
                     mock.patch("macrice.de.capture.shutil.which",
                                side_effect=lambda name: f"/usr/bin/{name}"), \
                     mock.patch("macrice.de.capture.subprocess.run", return_value=response) as run:
                    with self.assertRaises(capture.CaptureError):
                        capture.capture(destination, mode="region")
                    self.assertEqual(run.call_count, 1)
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_riceshot_cli_rejects_cross_command_and_ambiguous_mode_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = str(Path(folder) / "no.png")
            for args in (
                ["de", "shot", "--monitor", "eDP-1", "--output", dest],
                ["de", "shot", "--shot-mode", "output", "--output", dest],
                ["de", "shot", "--shot-mode", "region", "--monitor", "eDP-1", "--output", dest],
                ["de", "capture", "--shot-mode", "region", "--output", dest],
                ["de", "catalog", "--monitor", "eDP-1"],
                ["de", "capture", "--clipboard", "--output", dest],
                ["de", "shot", "--clipboard", "--output", dest],
            ):
                with self.subTest(args=args), mock.patch("sys.stderr"):
                    self.assertEqual(cli(args), 1)
            self.assertFalse(Path(dest).exists())

    def test_riceshot_clipboard_copies_without_leaving_a_screenshot(self):
        captured_locations = []

        def fake_run(command, **kwargs):
            if command[0] == "/usr/bin/grim":
                kwargs["stdout"].write(png())
            else:
                self.assertEqual(command, ["/usr/bin/wl-copy", "--type", "image/png"])
                stream = kwargs["stdin"]
                captured_locations.append(Path(stream.name))
                self.assertEqual(stream.read(), png())
                self.assertTrue(Path(stream.name).is_file())
                self.assertEqual(Path(stream.name).stat().st_mode & 0o777, 0o600)
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-test"}), \
             mock.patch("macrice.de.capture.shutil.which",
                        side_effect=lambda name: f"/usr/bin/{name}"), \
             mock.patch("macrice.de.capture.subprocess.run", side_effect=fake_run) as runner, \
             mock.patch("builtins.print") as printer:
            self.assertEqual(cli(["de", "shot", "--clipboard", "--json"]), 0)

        report = json.loads(printer.call_args.args[0])
        self.assertEqual(report["capture"]["destination"], "clipboard")
        self.assertTrue(report["capture"]["clipboard_updated"])
        self.assertNotIn("path", report["capture"])
        self.assertNotIn("mutates_active_desktop", report["capture"])
        self.assertEqual(runner.call_count, 2)
        self.assertFalse(captured_locations[0].exists())
        self.assertFalse(captured_locations[0].parent.exists())

    def test_riceshot_clipboard_failure_cleans_temporary_pixels(self):
        seen = []

        def fake_run(command, **kwargs):
            if command[0] == "/usr/bin/grim":
                kwargs["stdout"].write(png())
                return subprocess.CompletedProcess(command, 0)
            seen.append(Path(kwargs["stdin"].name))
            raise subprocess.CalledProcessError(1, command)

        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-test"}), \
             mock.patch("macrice.de.capture.shutil.which",
                        side_effect=lambda name: f"/usr/bin/{name}"), \
             mock.patch("macrice.de.capture.subprocess.run", side_effect=fake_run), \
             mock.patch("builtins.print") as printer:
            self.assertEqual(cli(["de", "shot", "--clipboard", "--json"]), 2)
        report = json.loads(printer.call_args.args[0])
        self.assertEqual(report["error"]["code"], "clipboard_failed")
        self.assertFalse(seen[0].parent.exists())
        self.assertNotIn("riceshot-", json.dumps(report))

        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-test"}), \
             mock.patch("macrice.de.capture.shutil.which",
                        side_effect=lambda name: None if name == "wl-copy" else "/usr/bin/grim"), \
             mock.patch("macrice.de.capture.subprocess.run") as runner:
            with self.assertRaisesRegex(capture.CaptureError, "requires wl-copy"):
                capture.copy_to_clipboard()
            runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
