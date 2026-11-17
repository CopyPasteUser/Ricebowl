"""RiceSpice must not silently discard a real Linux-service click."""

import threading
import unittest
from concurrent.futures import Future
from types import SimpleNamespace

from macrice.de.settings import RiceSpiceWindow


class RiceSpiceBusyActionTests(unittest.TestCase):
    def _page(self):
        pending, idle, states = [], [], []
        def submit(work):
            task = Future()
            pending.append((work, task))
            return task
        page = SimpleNamespace(
            closed=False, busy=False, generation=0,
            worker_slots=threading.BoundedSemaphore(1),
            executor=SimpleNamespace(submit=submit),
            GLib=SimpleNamespace(idle_add=idle.append),
            _state=states.append,
            _ricepop_open_pending=False, _ricepop_dirty=False,
        )
        return page, pending, idle, states

    def test_busy_click_explains_retry_without_delayed_unsafe_replay(self):
        page, pending, idle, states = self._page()
        actions = []
        RiceSpiceWindow._background(page, lambda: "Bluetooth inventory",
                                    lambda value: states.append("read:" + value))
        self.assertTrue(page.busy)
        self.assertEqual(len(pending), 1)
        # The second explicit click could change a real network/audio/
        # Bluetooth service. Never apply a stale mutation later by guessing.
        RiceSpiceWindow._background(page, lambda: actions.append("disable Wi-Fi"),
                                    lambda _value: None)
        self.assertEqual(len(pending), 1)
        self.assertEqual(actions, [])
        self.assertIn("retry this action", states[-1])
        pending[0][1].set_result("Bluetooth inventory")
        self.assertEqual(len(idle), 1)
        idle[0]()
        self.assertFalse(page.busy)
        self.assertEqual(actions, [])
        self.assertEqual(states[-1], "read:Bluetooth inventory")

    def test_window_close_never_reports_busy_or_submits_more_work(self):
        page, pending, _idle, states = self._page()
        page.busy = True
        page.closed = True
        RiceSpiceWindow._background(page, lambda: "unsafe", lambda _: None)
        self.assertEqual(states, [])
        self.assertEqual(pending, [])

    def test_worker_slot_contention_keeps_existing_unavailable_feedback(self):
        page, pending, _idle, states = self._page()
        self.assertTrue(page.worker_slots.acquire(blocking=False))
        RiceSpiceWindow._background(page, lambda: "will not execute", lambda _: None)
        self.assertEqual(pending, [])
        self.assertFalse(page.busy)
        self.assertIn("Another system request", states[-1])
        page.worker_slots.release()


if __name__ == "__main__":
    unittest.main()
