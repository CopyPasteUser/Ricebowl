"""Bounded, volatile RiceClip pinned entries and stale-snapshot protection."""

import json
import socket
import unittest
from unittest import mock

from macrice.de import clip


def insert(history, text):
    return history.handle({"op": "ingest", "text": text, "state": "data"})


def change_pin(history, operation, index, *, revision=None, session_id=None):
    return history.handle({
        "op": operation,
        "index": index,
        "revision": history.revision if revision is None else revision,
        "session_id": history.session_id if session_id is None else session_id,
    })


class PinHistoryTests(unittest.TestCase):
    def test_pin_stays_visible_when_unpinned_history_rolls_over(self):
        history = clip.History()
        insert(history, "keep-private")
        for index in range(4):
            insert(history, f"entry-{index}")
        receipt = change_pin(history, "pin", 4)
        self.assertEqual(receipt["pinned"], True)
        self.assertEqual(history.items[0], "keep-private")
        self.assertEqual(history.handle({"op": "status"})["pinned_count"], 1)

        for index in range(30):
            insert(history, f"next-{index}")
        self.assertEqual(len(history.items), clip.MAX_ITEMS)
        self.assertEqual(history.items[0], "keep-private")
        listing = history.handle({"op": "list"})
        self.assertTrue(listing["items"][0]["pinned"])
        self.assertTrue(all(not item["pinned"] for item in listing["items"][1:]))
        self.assertFalse(listing.get("persistent", False))
        self.assertEqual(listing["items"][0]["preview"], "keep-private")

    def test_limits_are_enforced_without_eviction_of_pins(self):
        history = clip.History()
        for index in range(clip.MAX_ITEMS):
            insert(history, f"original-{index}")
        for index in range(clip.MAX_PINS):
            receipt = change_pin(history, "pin", clip.MAX_ITEMS - index - 1)
            self.assertTrue(receipt["pinned"])
        self.assertEqual(history.handle({"op": "status"})["pinned_count"], 5)
        before = history.items[:]
        revision = history.revision
        with self.assertRaises(clip.ClipError) as raised:
            change_pin(history, "pin", clip.MAX_PINS)
        self.assertEqual(raised.exception.code, "pin_limit")
        self.assertEqual(history.items, before)
        self.assertEqual(history.revision, revision)
        for i in range(clip.MAX_ITEMS * 2):
            insert(history, f"new-{i}")
        self.assertEqual(len(history.pins), 5)
        self.assertTrue(all(item in history.pins for item in history.items[:5]))
        self.assertTrue(all(item not in history.pins for item in history.items[5:]))

    def test_reordering_and_idempotence_keep_revision_truthful(self):
        history = clip.History()
        for item in ("A", "B", "C"):
            insert(history, item)
        self.assertEqual(history.items, ["C", "B", "A"])
        change_pin(history, "pin", 2)
        self.assertEqual(history.items, ["A", "C", "B"])
        revision = history.revision
        receipt = change_pin(history, "pin", 0)
        self.assertEqual(receipt["revision"], revision)
        self.assertEqual(history.revision, revision)
        # Another newly pinned item joins the pinned prefix.
        change_pin(history, "pin", 2)
        self.assertEqual(history.items, ["B", "A", "C"])
        # Unpin keeps an item in the recent-unpinned part, not at the end.
        change_pin(history, "unpin", 0)
        self.assertEqual(history.items, ["A", "B", "C"])
        rev = history.revision
        self.assertFalse(change_pin(history, "unpin", 1)["pinned"])
        self.assertEqual(history.revision, rev)
        insert(history, "A")
        self.assertEqual(history.items, ["A", "B", "C"])
        self.assertEqual(history.revision, rev)
        insert(history, "B")
        self.assertEqual(history.items, ["A", "B", "C"])
        self.assertEqual(history.revision, rev)

    def test_new_unpinned_content_never_displaces_pinned_prefix(self):
        history = clip.History()
        for item in ("a", "b", "c"):
            insert(history, item)
        change_pin(history, "pin", 2)
        change_pin(history, "pin", 2)
        self.assertEqual(history.items, ["b", "a", "c"])
        insert(history, "new")
        self.assertEqual(history.items, ["b", "a", "new", "c"])
        insert(history, "a")
        self.assertEqual(history.items, ["a", "b", "new", "c"])

    def test_stale_and_malformed_pin_mutations_fail_closed(self):
        history = clip.History()
        insert(history, "secret-value")
        snapshot = history.handle({"op": "list"})
        insert(history, "new")
        for operation in ("pin", "unpin"):
            with self.subTest(operation=operation):
                with self.assertRaises(clip.ClipError) as exc:
                    change_pin(history, operation, 0,
                               revision=snapshot["revision"])
                self.assertEqual(exc.exception.code, "stale_history")
        another = clip.History()
        insert(another, "different-value")
        self.assertEqual(another.revision, 1)
        with self.assertRaises(clip.ClipError) as exc:
            change_pin(another, "pin", 0,
                       session_id=history.session_id,
                       revision=another.revision)
        self.assertEqual(exc.exception.code, "stale_history")
        for index in (True, -1, 999, "0"):
            with self.subTest(index=index):
                with self.assertRaises(clip.ClipError):
                    change_pin(another, "pin", index)
        for required in ("revision", "session_id"):
            request = {"op": "pin", "index": 0,
                       "revision": another.revision,
                       "session_id": another.session_id}
            request.pop(required)
            with self.assertRaises(clip.ClipError):
                another.handle(request)
        self.assertFalse(history.pins)
        self.assertFalse(another.pins)

    def test_pin_state_is_volatile_and_clear_erases_it(self):
        history = clip.History()
        insert(history, "test-only")
        change_pin(history, "pin", 0)
        old_id = history.session_id
        self.assertEqual(history.handle({"op": "status"})["pinned_count"], 1)
        history.handle({"op": "clear"})
        self.assertEqual(history.items, [])
        self.assertEqual(history.pins, set())
        self.assertEqual(history.handle({"op": "status"})["pinned_count"], 0)
        next_watcher = clip.History()
        self.assertNotEqual(old_id, next_watcher.session_id)
        self.assertFalse(next_watcher.items)
        self.assertFalse(next_watcher.pins)

    def test_protocol_refuses_stale_index_without_exposing_private_text(self):
        history = clip.History()
        insert(history, "ultra-secret-value")
        before = history.handle({"op": "list"})
        insert(history, "moved")
        left, right = socket.socketpair()
        with left, right:
            right.sendall(json.dumps({
                "op": "pin", "index": 0,
                "revision": before["revision"],
                "session_id": before["session_id"],
            }).encode() + b"\n")
            clip._transact(left, history)
            response = right.recv(1024)
        self.assertEqual(json.loads(response)["error"], "stale_history")
        self.assertNotIn(b"ultra-secret-value", response)
        self.assertFalse(history.pins)


if __name__ == "__main__":
    unittest.main()
