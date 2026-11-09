"""Agent render-contract boundaries before any compositor processes run."""

import json
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from macrice.cli import main as cli
from macrice.de import catalog, creator_contract, render


class HeadlessRenderTests(unittest.TestCase):
    def test_catalog_exposes_exact_headless_requirements(self):
        spec = catalog.describe()["authoring"]["render"]
        self.assertEqual(spec, creator_contract.describe_render())
        self.assertFalse(spec["requires_running_wayland_session"])
        self.assertTrue(spec["creates_temporary_compositor"])
        self.assertFalse(spec["mutates_active_desktop"])
        self.assertIn("riceplate-native", spec["requires_binaries"])

    def test_invalid_requests_rejected_before_process_spawn(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "new.png"
            existing = Path(folder) / "existing.png"
            existing.write_text("keep")
            symlink = Path(folder) / "link.png"
            symlink.symlink_to(existing)
            for output, width, height, scale in (
                (Path("relative.png"), 1366, 768, 1.0),
                (existing, 1366, 768, 1.0),
                (symlink, 1366, 768, 1.0),
                (dest, 300, 768, 1.0),
                (dest, 1366, 300, 1.0),
                (dest, 4096, 4096, 1.0),
                (dest, 1366, 768, 1.1),
            ):
                with self.subTest(output=output, width=width, height=height, scale=scale), \
                     mock.patch("macrice.de.render.subprocess.Popen") as spawn:
                    with self.assertRaises(render.RenderError) as error:
                        render.render("classic", output, width=width, height=height, scale=scale)
                    self.assertEqual(error.exception.code, "invalid_render_request")
                    spawn.assert_not_called()
            self.assertEqual(existing.read_text(), "keep")

    def test_missing_recipe_and_native_dependencies_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "new.png"
            with mock.patch("macrice.de.render.subprocess.Popen") as spawn:
                with self.assertRaises(render.RenderError) as raised:
                    render.render("../../../invalid", dest)
                self.assertEqual(raised.exception.code, "invalid_render_request")
                spawn.assert_not_called()
            with mock.patch("macrice.de.render.os.geteuid", return_value=1000), \
                 mock.patch("macrice.de.render.shutil.which", return_value=None), \
                 mock.patch("macrice.de.render.subprocess.Popen") as spawn:
                with self.assertRaises(render.RenderError) as raised:
                    render.render("classic", dest)
                self.assertEqual(raised.exception.code, "render_unavailable")
                spawn.assert_not_called()
            self.assertFalse(dest.exists())

    def test_output_detection_parses_only_one_safe_compositor_name(self):
        good = subprocess.CompletedProcess([], 0, stdout="HEADLESS-1 1920x1080\n  1920x1080\n")
        with mock.patch("macrice.de.render.subprocess.run", return_value=good):
            self.assertEqual(render._output_name("/usr/bin/wlr-randr", dict(os.environ)), "HEADLESS-1")
        bad = subprocess.CompletedProcess([], 0, stdout="bad/name\n")
        with mock.patch("macrice.de.render.subprocess.run", return_value=bad):
            with self.assertRaises(render.RenderError):
                render._output_name("/usr/bin/wlr-randr", dict(os.environ))

    def test_stop_terminates_owned_group_and_reaps(self):
        process = mock.Mock()
        process.pid = 12345
        process.poll.return_value = None
        process.wait.return_value = 0
        with mock.patch("macrice.de.render.os.killpg") as kill:
            render._stop(process)
        kill.assert_called_once_with(12345, render.signal.SIGTERM)
        process.wait.assert_called_once_with(timeout=3)

    def test_stop_escalates_after_timeout(self):
        process = mock.Mock()
        process.pid = 12345
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("labwc", 3), 0]
        with mock.patch("macrice.de.render.os.killpg") as kill:
            render._stop(process)
        self.assertEqual(kill.call_args_list, [
            mock.call(12345, render.signal.SIGTERM),
            mock.call(12345, render.signal.SIGKILL),
        ])
        self.assertEqual(process.wait.call_count, 2)

    def test_cleanup_continues_after_child_failure(self):
        children = [mock.Mock(), mock.Mock(), mock.Mock()]
        with mock.patch("macrice.de.render._stop",
                        side_effect=[OSError("injected"), None, None]) as stop:
            with self.assertRaises(render.RenderError) as raised:
                render._cleanup_children(children)
        self.assertEqual(raised.exception.code, "render_failed")
        self.assertEqual([call.args[0] for call in stop.call_args_list],
                         list(reversed(children)))

    def test_stop_does_not_signal_reaped_pid(self):
        process = mock.Mock()
        process.poll.return_value = 0
        with mock.patch("macrice.de.render.os.killpg") as kill:
            render._stop(process)
        kill.assert_not_called()
        process.wait.assert_called_once_with()

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux process sessions")
    def test_stop_reaps_descendant_after_session_leader_exits(self):
        """An exited compositor must not leave a still-running child behind."""
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / "descendant.pid"
            token = "ricebowl-test-" + str(os.getpid())
            script = (
                "import os, signal, sys, time\n"
                "if os.fork() == 0:\n"
                "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "    with open(sys.argv[1], 'w') as marker: marker.write(str(os.getpid()))\n"
                "    time.sleep(30)\n"
                "else:\n"
                "    os._exit(0)\n"
            )
            env = {**os.environ, "RICEBOWL_RENDER_SESSION": token}
            leader = subprocess.Popen([sys.executable, "-c", script, str(marker)],
                                      start_new_session=True, env=env)
            descendant = None
            try:
                deadline = time.monotonic() + 3
                # The descendant creates its marker before writing its PID.
                # Waiting for existence alone can race with that write.
                while time.monotonic() < deadline:
                    try:
                        marker_pid = marker.read_text().strip()
                    except FileNotFoundError:
                        marker_pid = ""
                    if marker_pid.isdecimal():
                        descendant = int(marker_pid)
                        break
                    time.sleep(0.02)
                self.assertIsNotNone(descendant, "descendant did not publish its PID")
                leader.wait(timeout=2)
                self.assertIn(descendant, render._owned_session_pids(leader.pid, token),
                              "orphan is not discoverable as an owned process")
                render._stop(leader, token)
                stat = Path(f"/proc/{descendant}/stat")
                def stopped():
                    try:
                        return stat.read_text().split(") ")[1][0] == "Z"
                    except (FileNotFoundError, ProcessLookupError):
                        # /proc entries may vanish during read() or between lookups.
                        return True
                deadline = time.monotonic() + 2
                while not stopped() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(stopped(),
                                "orphan descendant still running")
            finally:
                if descendant is not None:
                    try:
                        os.kill(descendant, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if leader.poll() is None:
                    leader.kill()
                leader.wait()

    def test_renderer_failures_preserve_output_and_remove_staging(self):
        """Failures at each boundary must leave no published partial capture."""
        for failure in ("compositor", "renderer", "grim", "timeout", "interrupt",
                        "receipt", "corrupt-file", "cleanup", "concurrent-output", "success"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "capture.png"
                spawned = []

                def fake_spawn(command, **_kwargs):
                    if failure == "compositor" and not spawned:
                        raise OSError("labwc unavailable")
                    if failure == "renderer" and "riceplate-native" in command[0]:
                        raise OSError("renderer unavailable")
                    process = mock.Mock()
                    process.pid = 40000 + len(spawned)
                    process.poll.return_value = None
                    process.wait.return_value = 0
                    if any(str(part).endswith("/launcher.py") for part in command):
                        if failure == "concurrent-output":
                            target.write_bytes(b"KEEP")
                        stage = Path(command[command.index("--output") + 1])
                        stage.write_bytes(b"validated capture")
                        capture_record = {"width": 1024, "height": 768,
                                          "bytes": len(b"validated capture"),
                                          "sha256": hashlib.sha256(b"validated capture").hexdigest()}
                        if failure == "corrupt-file":
                            capture_record["sha256"] = "0" * 64
                        process.returncode = 2 if failure == "grim" else 0
                        process.communicate.return_value = (
                            b"not JSON" if failure == "receipt" else
                            json.dumps({"ok": True, "capture": capture_record}).encode(), b"")
                        if failure == "timeout":
                            process.communicate.side_effect = subprocess.TimeoutExpired("grim", 35)
                        if failure == "interrupt":
                            process.communicate.side_effect = KeyboardInterrupt
                    spawned.append(process)
                    return process

                def fake_cleanup(_children, _token):
                    if failure == "cleanup":
                        raise render.RenderError("render_failed")

                with (mock.patch("macrice.de.render.os.geteuid", return_value=1000),
                      mock.patch("macrice.de.render.shutil.which", side_effect=lambda name: "/bin/" + name),
                      mock.patch("macrice.de.render.Path.is_socket", return_value=True),
                      mock.patch("macrice.de.render._output_name", return_value="HEADLESS-1"),
                      mock.patch("macrice.de.render.subprocess.run"),
                      mock.patch("macrice.de.render.subprocess.Popen", side_effect=fake_spawn),
                      mock.patch("macrice.de.render._cleanup_children", side_effect=fake_cleanup),
                      mock.patch("macrice.de.render.time.sleep")):
                    if failure == "success":
                        result = render.render("classic", target, width=1024, height=768)
                        self.assertEqual(result["geometry"]["width"], 1024)
                    elif failure == "interrupt":
                        with self.assertRaises(KeyboardInterrupt):
                            render.render("classic", target, width=1024, height=768)
                    else:
                        with self.assertRaises(render.RenderError) as raised:
                            render.render("classic", target, width=1024, height=768)
                        self.assertEqual(raised.exception.code, "render_failed")

                if failure == "concurrent-output":
                    self.assertEqual(target.read_bytes(), b"KEEP")
                elif failure == "success":
                    self.assertEqual(target.read_bytes(), b"validated capture")
                else:
                    self.assertFalse(target.exists())
                self.assertEqual(list(Path(folder).glob(".ricebowl-render-*")), [])

    @unittest.skipUnless(os.environ.get("RICEBOWL_TEST_NATIVE_RENDER") == "1",
                         "real labwc/RicePlate CI only")
    def test_real_headless_success_and_injected_failures_leave_no_processes(self):
        """Run only after native CI builds RicePlate and installs labwc."""
        import shutil

        def private_runtimes():
            return set(Path(tempfile.gettempdir()).glob("ricebowl-render-*"))

        def live_renderer_processes():
            owned = []
            for proc in Path("/proc").iterdir():
                if not proc.name.isdecimal():
                    continue
                try:
                    if (proc / "stat").read_text().rsplit(") ", 1)[1].split()[0] == "Z":
                        continue
                    if b"RICEBOWL_RENDER_SESSION=" in (proc / "environ").read_bytes():
                        owned.append(proc.name)
                except OSError:
                    continue
            return owned

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            recipe = root / "recipe.json"
            recipe.write_bytes((Path(__file__).parent / "fixtures" /
                                "riceplate-desktop-v5.json").read_bytes())
            recipe.chmod(0o600)
            before = private_runtimes()
            output = root / "success.png"
            receipt = render.render(str(recipe), output, width=1024, height=768)
            self.assertEqual(receipt["output"]["width"], 1024)
            self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(private_runtimes(), before)
            self.assertFalse(live_renderer_processes())

            false_dir = root / "false-bin"
            false_dir.mkdir()
            for binary in ("labwc", "riceplate-native", "grim"):
                link = false_dir / binary
                link.symlink_to(shutil.which("false") or "/bin/false")
                # Override only the selected executable; keep other tools real.
                path = str(false_dir) + os.pathsep + os.environ["PATH"]
                for other in ("labwc", "riceplate-native", "grim"):
                    if other != binary:
                        (false_dir / other).unlink(missing_ok=True)
                failure_output = root / (binary + ".png")
                with mock.patch.dict(os.environ, {"PATH": path}):
                    with self.assertRaises(render.RenderError):
                        render.render(str(recipe), failure_output, width=1024, height=768)
                self.assertFalse(failure_output.exists())
                self.assertEqual(private_runtimes(), before)
                self.assertFalse(list(root.glob(".ricebowl-render-*")))
                self.assertFalse(live_renderer_processes())
                link.unlink()

    def test_json_cli_failure_is_stable_and_does_not_expose_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "private.png"
            with mock.patch("builtins.print") as printer:
                self.assertEqual(cli(["de", "render", "--recipe", "classic", "--output",
                                      str(target), "--width", "320", "--json"]), 2)
            error = json.loads(printer.call_args.args[0])
            self.assertFalse(error["ok"])
            self.assertEqual(error["error"]["code"], "invalid_render_request")
            self.assertNotIn(folder, json.dumps(error))
            self.assertFalse(target.exists())

    def test_geometry_flags_do_not_leak_to_other_commands(self):
        for arguments in (["de", "catalog", "--width", "1024"],
                          ["de", "capture", "--height", "768"],
                          ["de", "render", "--nested"],
                          ["de", "render", "--panel", "native"]):
            with self.subTest(arguments=arguments), mock.patch("sys.stderr"):
                self.assertEqual(cli(arguments), 1)


if __name__ == "__main__":
    unittest.main()
