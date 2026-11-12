"""RiceClip browser: revision-safe copy and a nonresident GTK entrypoint."""

import io
import json
import socket
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from macrice.cli import main as cli
from macrice.de import clip, clip_ui


class ClipRevisionTests(unittest.TestCase):
    def test_copy_rejects_reordered_history_before_wl_copy(self):
        history = clip.History()
        history.handle({"op": "ingest", "state": "data", "text": "first"})
        history.handle({"op": "ingest", "state": "data", "text": "second"})
        snapshot = history.handle({"op": "list"})
        self.assertEqual(snapshot["revision"], 2)
        self.assertEqual(snapshot["items"][1]["preview"], "first")

        history.handle({"op": "ingest", "state": "data", "text": "third"})
        with mock.patch.object(clip.shutil, "which") as which, \
             mock.patch.object(clip.subprocess, "run") as run:
            with self.assertRaises(clip.ClipError) as raised:
                history.handle({"op": "copy", "index": 1,
                                "revision": snapshot["revision"]})
            self.assertEqual(raised.exception.code, "stale_history")
            which.assert_not_called()
            run.assert_not_called()

        with mock.patch.object(clip.shutil, "which", return_value="/usr/bin/wl-copy"), \
             mock.patch.object(clip.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0)) as run:
            history.handle({"op": "copy", "index": 1,
                            "revision": history.revision})
        self.assertEqual(run.call_args.kwargs["input"], b"second")

    def test_revision_moves_only_when_list_changes(self):
        history = clip.History()
        self.assertEqual(history.handle({"op": "list"})["revision"], 0)
        history.handle({"op": "ingest", "state": "data", "text": "a"})
        self.assertEqual(history.revision, 1)
        history.handle({"op": "ingest", "state": "data", "text": "a"})
        self.assertEqual(history.revision, 1)
        history.handle({"op": "pause"})
        history.handle({"op": "resume"})
        self.assertEqual(history.revision, 1)
        history.handle({"op": "clear"})
        self.assertEqual(history.revision, 2)
        history.handle({"op": "clear"})
        self.assertEqual(history.revision, 2)

    def test_copy_rejects_restarted_watcher_with_same_revision(self):
        old = clip.History()
        new = clip.History()
        old.handle({"op": "ingest", "state": "data", "text": "old secret"})
        new.handle({"op": "ingest", "state": "data", "text": "new secret"})
        self.assertEqual(old.revision, new.revision)
        self.assertNotEqual(old.session_id, new.session_id)
        with mock.patch.object(clip.shutil, "which") as which:
            with self.assertRaises(clip.ClipError) as raised:
                new.handle({"op": "copy", "index": 0, "revision": old.revision,
                            "session_id": old.session_id})
            self.assertEqual(raised.exception.code, "stale_history")
            which.assert_not_called()

    def test_bogus_revision_never_runs_clipboard_process(self):
        history = clip.History()
        history.handle({"op": "ingest", "state": "data", "text": "private"})
        with mock.patch.object(clip.shutil, "which") as which:
            for revision in (True, "1", -1, 0):
                with self.subTest(revision=revision):
                    with self.assertRaises(clip.ClipError):
                        history.handle({"op": "copy", "index": 0,
                                        "revision": revision})
            which.assert_not_called()
        # Older explicit CLI index-only clients are intentionally compatible.
        with mock.patch.object(clip.shutil, "which", return_value="/usr/bin/wl-copy"), \
             mock.patch.object(clip.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0)):
            self.assertTrue(history.handle({"op": "copy", "index": 0})["ok"])

    def test_revision_is_roundtripped_through_socket_protocol(self):
        left, right = socket.socketpair()
        history = clip.History()
        history.handle({"op": "ingest", "state": "data", "text": "private"})
        with left, right:
            right.sendall(b'{"op":"copy","index":0,"revision":0}\n')
            clip._transact(left, history)
            payload = json.loads(right.recv(256))
        self.assertEqual(payload, {"ok": False, "error": "stale_history"})


class ClipBrowserModelTests(unittest.TestCase):
    @staticmethod
    def _status(revision=5, count=2):
        return {"ok": True, "revision": revision, "session_id": "a" * 32,
                "paused": False,
                "count": count, "persistent": False, "pinned_count": 0, "max_pins": 5}

    @staticmethod
    def _listing(revision=5):
        return {"ok": True, "revision": revision, "session_id": "a" * 32,
                "items": [
            {"index": 0, "preview": "Hello world", "characters": 11, "pinned": False},
            {"index": 1, "preview": "Grüße ☀", "characters": 7, "pinned": False},
        ]}

    def test_snapshot_is_bounded_and_searches_only_safe_previews(self):
        with mock.patch.object(clip_ui.clip, "request",
                               side_effect=[self._status(), self._listing()]) as request:
            snapshot = clip_ui.read_snapshot()
        self.assertEqual(request.call_args_list,
                         [mock.call("status"), mock.call("list")])
        self.assertEqual(snapshot.revision, 5)
        self.assertEqual([row.index for row in
                          clip_ui.visible_rows(snapshot, "GRÜßE")], [1])
        self.assertEqual(clip_ui.visible_rows(snapshot, "not in previews"), ())

    def test_empty_and_filtered_history_have_explicit_ui_states(self):
        empty = clip_ui.ClipSnapshot(0, "a" * 32, False, ())
        self.assertIn("No clipboard text", clip_ui.snapshot_message(empty, ""))
        paused = clip_ui.ClipSnapshot(
            4, "a" * 32, True, (clip_ui.ClipRow(0, "hello", 5),))
        self.assertIn("No previews match", clip_ui.snapshot_message(paused, "not here"))
        self.assertIn("Paused", clip_ui.snapshot_message(paused, "hello"))
        self.assertIn("1 item", clip_ui.snapshot_message(paused, "hello"))

    def test_status_list_race_retries_then_fails_closed(self):
        with mock.patch.object(clip_ui.clip, "request",
                               side_effect=[self._status(5), self._listing(6),
                                            self._status(6), self._listing(6)]):
            self.assertEqual(clip_ui.read_snapshot().revision, 6)
        with mock.patch.object(clip_ui.clip, "request",
                               side_effect=[self._status(5), self._listing(6),
                                            self._status(6), self._listing(7)]):
            with self.assertRaises(clip.ClipError) as raised:
                clip_ui.read_snapshot()
        self.assertEqual(raised.exception.code, "stale_history")

    def test_watcher_identity_change_during_snapshot_fails_closed(self):
        old = self._status()
        changed = self._listing()
        changed["session_id"] = "b" * 32
        with mock.patch.object(clip_ui.clip, "request",
                               side_effect=[old, changed, old, changed]):
            with self.assertRaises(clip.ClipError) as raised:
                clip_ui.read_snapshot()
        self.assertEqual(raised.exception.code, "stale_history")

    def test_snapshot_rejects_malformed_or_oversized_untrusted_results(self):
        invalid = [
            {"ok": True, "revision": 5, "session_id": "a" * 32, "items": [
                {"index": True, "preview": "abc", "characters": 3, "pinned": False}]},
            {"ok": True, "revision": 5, "session_id": "a" * 32, "items": [
                {"index": 0, "preview": "x" * 81, "characters": 81, "pinned": False}]},
            {"ok": True, "revision": 5, "session_id": "a" * 32, "items": [
                {"index": 0, "preview": "abc", "characters": -1, "pinned": False}]},
            {"ok": True, "revision": 5, "session_id": "a" * 32, "items": []},
        ]
        for listing in invalid:
            with self.subTest(listing=listing):
                with mock.patch.object(clip_ui.clip, "request",
                                       side_effect=[self._status(count=1), listing]):
                    with self.assertRaises(clip.ClipError):
                        clip_ui.read_snapshot()

    def test_pinned_snapshot_and_local_preview_search(self):
        status = self._status()
        status["pinned_count"] = 1
        listing = self._listing()
        listing["items"][0]["pinned"] = True
        with mock.patch.object(clip_ui.clip, "request",
                               side_effect=[status, listing]):
            snapshot = clip_ui.read_snapshot()
        self.assertTrue(snapshot.rows[0].pinned)
        self.assertFalse(snapshot.rows[1].pinned)
        self.assertEqual([row.index for row in
                          clip_ui.visible_rows(snapshot, "grüße")], [1])
        self.assertIn("1 pinned", clip_ui.snapshot_message(snapshot, ""))

    def test_reject_inconsistent_pinned_metadata(self):
        for malformed in ("true", 1, None, [], {}):
            status = self._status()
            status["pinned_count"] = 1
            listing = self._listing()
            listing["items"][0]["pinned"] = malformed
            with self.subTest(malformed=malformed):
                with mock.patch.object(clip_ui.clip, "request",
                                       side_effect=[status, listing]):
                    with self.assertRaises(clip.ClipError):
                        clip_ui.read_snapshot()
        status = self._status()
        status["pinned_count"] = 1
        listing = self._listing()  # zero pinned entries
        with mock.patch.object(clip_ui.clip, "request",
                               side_effect=[status, listing]):
            with self.assertRaises(clip.ClipError):
                clip_ui.read_snapshot()

    def test_restore_always_supplies_snapshot_revision(self):
        snapshot = clip_ui.ClipSnapshot(27, "a" * 32, False,
                                       (clip_ui.ClipRow(3, "sample", 6),))
        with mock.patch.object(clip_ui.clip, "request") as request:
            clip_ui.restore_row(snapshot.rows[0], snapshot)
        request.assert_called_once_with("copy", index=3, revision=27,
                                        session_id="a" * 32)

    def test_gui_cli_is_explicit_and_never_starts_watcher(self):
        with mock.patch.object(clip_ui, "launch") as launch, \
             mock.patch.object(clip, "watch") as watcher:
            self.assertEqual(cli(["de", "clip", "--clip-op", "gui"]), 0)
            launch.assert_called_once_with()
            watcher.assert_not_called()
        with mock.patch.object(clip_ui, "launch") as launch, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(cli(["de", "clip", "--clip-op", "gui", "--json"]), 1)
            self.assertEqual(cli(["de", "clip", "--clip-op", "gui",
                                  "--clip-index", "0"]), 1)
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
