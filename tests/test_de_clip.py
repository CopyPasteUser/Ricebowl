"""RiceClip's opt-in in-memory history, socket boundary and CLI privacy gates."""

import json
import os
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from macrice.cli import main as cli
from macrice.de import clip


class ClipHistoryTests(unittest.TestCase):
    def test_history_dedup_limits_and_clear(self):
        state = clip.History()
        for i in range(30):
            state.handle({"op": "ingest", "state": "data", "text": f"line-{i}"})
        self.assertEqual(len(state.items), clip.MAX_ITEMS)
        self.assertEqual(state.items[0], "line-29")
        self.assertEqual(state.items[-1], "line-10")
        state.handle({"op": "ingest", "state": "data", "text": "line-15"})
        self.assertEqual(state.items[0], "line-15")
        self.assertEqual(state.items.count("line-15"), 1)
        state.handle({"op": "clear"})
        self.assertEqual(state.items, [])

    def test_pausing_and_untrusted_payloads(self):
        state = clip.History()
        for content, protocol_state in (
            ("secret", "sensitive"), ("cleared", "nil"), ("", "data"),
            ("a\x00b", "data"), ("a" * (clip.MAX_TEXT_BYTES + 1), "data"),
        ):
            self.assertFalse(state.handle({"op": "ingest", "text": content,
                                           "state": protocol_state})["recorded"])
        self.assertEqual(state.items, [])
        state.handle({"op": "pause"})
        state.handle({"op": "ingest", "text": "do not keep", "state": "data"})
        self.assertEqual(state.items, [])
        state.handle({"op": "resume"})
        state.handle({"op": "ingest", "text": "grüße 🌿", "state": "data"})
        self.assertEqual(state.items, ["grüße 🌿"])
        self.assertFalse(state.handle({"op": "status"})["persistent"])
        self.assertEqual(state.handle({"op": "list"})["items"][0]["preview"], "grüße 🌿")

    def test_copy_is_explicit_and_does_not_change_history_on_failure(self):
        state = clip.History()
        state.handle({"op": "ingest", "state": "data", "text": "📋 content"})
        with self.assertRaises(clip.ClipError):
            state.handle({"op": "copy", "index": True})
        with self.assertRaises(clip.ClipError):
            state.handle({"op": "copy", "index": 2})
        with mock.patch.object(clip.shutil, "which", return_value="/usr/bin/wl-copy"), \
             mock.patch.object(clip.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(state.handle({"op": "copy", "index": 0})["copied_index"], 0)
        self.assertEqual(run.call_args.args[0],
                         ["/usr/bin/wl-copy", "--type", "text/plain;charset=utf-8"])
        self.assertEqual(run.call_args.kwargs["input"], "📋 content".encode())
        with mock.patch.object(clip.shutil, "which", return_value="/usr/bin/wl-copy"), \
             mock.patch.object(clip.subprocess, "run", side_effect=OSError):
            with self.assertRaises(clip.ClipError) as raised:
                state.handle({"op": "copy", "index": 0})
        self.assertEqual(raised.exception.code, "copy_failed")
        self.assertEqual(state.items, ["📋 content"])

    def test_private_wayland_runtime_is_required(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": folder,
                                              "WAYLAND_DISPLAY": "wayland-test"}):
                self.assertEqual(clip.socket_path(), clip.socket_path())
                Path(folder).chmod(0o755)
                with self.assertRaises(clip.ClipError) as raised:
                    clip.socket_path()
                self.assertEqual(raised.exception.code, "unavailable")
                Path(folder).chmod(0o700)
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": folder,
                                              "WAYLAND_DISPLAY": ""}):
                with self.assertRaises(clip.ClipError):
                    clip.socket_path()


class ClipProtocolTests(unittest.TestCase):
    def test_socket_protocol_keeps_private_data_out_of_status_and_errors(self):
        left, right = socket.socketpair()
        history = clip.History()
        with left, right:
            right.sendall(json.dumps({"op": "ingest", "text": "passwordlike",
                                      "state": "data"}).encode() + b"\n")
            clip._transact(left, history)
            self.assertTrue(json.loads(right.recv(512))["recorded"])
        self.assertEqual(history.items, ["passwordlike"])
        left, right = socket.socketpair()
        with left, right:
            right.sendall(b'{"op":"invalid"}\n')
            clip._transact(left, history)
            response = right.recv(512)
        self.assertNotIn(b"passwordlike", response)
        self.assertEqual(json.loads(response)["error"], "invalid_request")

    def test_real_unix_socket_round_trip_and_cleanup(self):
        try:
            probe = socket.socket(socket.AF_UNIX)
        except PermissionError:
            self.skipTest("This executor blocks creating Unix sockets (EPERM)")
        else:
            probe.close()

        class Watcher:
            stopped = False

            def poll(self):
                return 0 if self.stopped else None

            def terminate(self):
                self.stopped = True

            def wait(self, timeout=None):
                return 0

        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": folder,
                                       "WAYLAND_DISPLAY": "wayland-test"}), \
             mock.patch.object(clip.shutil, "which", return_value="/usr/bin/wl-paste"), \
             mock.patch.object(clip.subprocess, "Popen", return_value=Watcher()) as popen, \
             mock.patch.object(clip.signal, "signal"):
            ready = threading.Event()
            errors = []

            def worker():
                try:
                    clip.watch(on_ready=ready.set)
                except clip.ClipError as exc:
                    errors.append(exc.code)

            running = threading.Thread(target=worker)
            running.start()
            try:
                self.assertTrue(ready.wait(timeout=2))
                self.assertEqual(clip.request("status")["count"], 0)
                self.assertTrue(clip.request("ingest", text="Hello ☀", state="data")["recorded"])
                self.assertEqual(clip.request("list")["items"][0]["preview"], "Hello ☀")
                clip.request("pause")
                self.assertFalse(clip.request("ingest", text="ignored", state="data")["recorded"])
                self.assertEqual(clip.request("status")["count"], 1)
                clip.request("clear")
                self.assertEqual(clip.request("status")["count"], 0)
                self.assertEqual(clip.socket_path().stat().st_mode & 0o777, 0o600)
                self.assertEqual(popen.call_args.args[0][1:4],
                                 ["--type", "text", "--watch"])
                self.assertTrue(popen.call_args.args[0][6].endswith("/launcher.py"))
            finally:
                Watcher.stopped = True
                running.join(timeout=3)
            self.assertFalse(running.is_alive())
            self.assertEqual(errors, ["watch_unavailable"])
            self.assertFalse(clip.socket_path().exists())

    def test_cli_error_is_json_and_no_implicit_watcher(self):
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": ""}), \
             mock.patch("builtins.print") as printer:
            self.assertEqual(cli(["de", "clip", "--json"]), 2)
        self.assertEqual(json.loads(printer.call_args.args[0])["error"]["code"], "unavailable")
        with mock.patch.object(clip, "watch") as watcher, mock.patch("sys.stderr"):
            self.assertEqual(cli(["de", "clip", "--clip-op", "copy"]), 1)
            self.assertEqual(cli(["de", "shot", "--clip-op", "clear"]), 1)
            self.assertEqual(cli(["de", "clip", "--clip-index", "0"]), 1)
        watcher.assert_not_called()


if __name__ == "__main__":
    unittest.main()
