"""scripts/gtk_keyboard.py: the real-keyboard helper shared by the SG2/SG3/SG4 GTK smokes.

The helper is exercised with a fake `wtype` and a fake focus ring, so the *logic* the smokes rely
on (pad key on every GTK key, Tab until the target holds focus, the one tolerated miss) stays
pinned where no compositor is available. The compositor receipts are in the smokes themselves.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import gtk_keyboard as gk  # noqa: E402


class PadKey(unittest.TestCase):
    def test_every_gtk_key_is_sent_with_the_trailing_pad_key_in_one_wtype_call(self):
        with mock.patch.object(gk, "wtype") as wtype, mock.patch.object(gk.time, "sleep"):
            gk.gtk_key("Tab")
            gk.gtk_key("Return", pause=0)
        self.assertEqual(wtype.call_args_list, [
            mock.call("-k", "Tab", "-k", gk.GTK_PAD_KEY), mock.call("-k", "Return", "-k", gk.GTK_PAD_KEY)])
        self.assertEqual(gk.GTK_PAD_KEY, "F35")

    def test_the_negative_control_really_is_unpadded(self):
        with mock.patch.object(gk, "wtype") as wtype:
            gk.unpadded_key("space")
        wtype.assert_called_once_with("-k", "space")

    def test_the_pad_key_is_unbound_in_the_shipped_labwc_config(self):
        rc = (Path(__file__).resolve().parents[1] / "macrice/de/resources/labwc/rc.xml").read_text()
        self.assertNotIn(gk.GTK_PAD_KEY, rc)


class Ring:
    """A fake window: Tab advances a ring of focus readings."""

    def __init__(self, ring, stuck=False):
        self.ring, self.index, self.stuck, self.presses = ring, 0, stuck, 0

    def focused(self):
        return self.ring[self.index]

    def key(self, name, pause=0.2):
        self.presses += 1
        if name == "Tab" and not self.stuck:
            self.index = (self.index + 1) % len(self.ring)


class TabTo(unittest.TestCase):
    def run_tab(self, ring, target, **kwargs):
        window = Ring(ring, kwargs.pop("stuck", False))
        with mock.patch.object(gk, "gtk_key", window.key), mock.patch.object(gk.time, "sleep"):
            return window, gk.tab_to(target, window.focused, **kwargs)

    def test_reaches_the_target_counting_presses_and_stops_there(self):
        window, presses = self.run_tab([["a"], ["b"], ["c"]], "c")
        self.assertEqual((presses, window.presses), (2, 2))

    def test_an_already_focused_target_needs_no_key(self):
        window, presses = self.run_tab([["a"], ["b"]], "a")
        self.assertEqual((presses, window.presses), (0, 0))

    def test_stops_without_an_accessible_are_tolerated_and_matches_can_be_custom(self):
        window, presses = self.run_tab([["a"], [], ["I reviewed the package contents (x)"]], "I reviewed",
                                       matches=lambda name: name.startswith("I reviewed"))
        self.assertEqual(presses, 2)

    def test_a_target_that_is_not_in_the_chain_fails_with_the_trail(self):
        with self.assertRaises(gk.Fail) as raised:
            self.run_tab([["a"], ["b"]], "missing", limit=5)
        self.assertIn("never reached", str(raised.exception))

    def test_a_tab_that_does_not_move_focus_fails_instead_of_hanging(self):
        with mock.patch.object(gk, "wait_for", side_effect=gk.Fail("timeout")):
            with self.assertRaises(gk.Fail) as raised:
                self.run_tab([["a"], ["b"]], "b", describe=lambda: "tree")
        self.assertIn("did not move GTK focus", str(raised.exception))
        self.assertIn("tree", str(raised.exception))


class Activate(unittest.TestCase):
    def activate(self, outcomes, busy, **kwargs):
        calls = iter(outcomes)
        presses = []

        def key(name, pause=0.2):
            presses.append(name)
        state = {"done": False}

        def done():
            if not state["done"]:
                state["done"] = next(calls)
            return state["done"]
        with mock.patch.object(gk, "gtk_key", key), mock.patch.object(gk.time, "sleep"), \
                mock.patch.object(gk, "wait_for", lambda predicate, message, timeout=0, **_: (
                    predicate() or (_ for _ in ()).throw(gk.Fail("timeout: " + message)))):
            result = gk.activate("Return", done, "the action", busy=busy, **kwargs)
        return result, presses

    def test_acts_on_the_first_press(self):
        self.assertEqual(self.activate([True], busy=lambda: False), (1, ["Return"]))

    def test_the_products_visible_busy_refusal_is_retried(self):
        result, presses = self.activate([False, False, True], busy=lambda: True)
        self.assertEqual((result, presses), (3, ["Return"] * 3))

    def test_a_silent_miss_is_a_failure_not_a_retry(self):
        with self.assertRaises(gk.Fail) as raised:
            self.activate([False, True], busy=lambda: False, describe=lambda: "tree")
        self.assertIn("neither acted nor produced the busy refusal", str(raised.exception))

    def test_a_permanently_busy_window_fails_after_the_attempts(self):
        with self.assertRaises(gk.Fail) as raised:
            self.activate([False] * 9, busy=lambda: True, attempts=3)
        self.assertIn("still refused as busy after 3 presses", str(raised.exception))


class Names(unittest.TestCase):
    def test_stop_name_is_the_accessible_name_part(self):
        self.assertEqual(gk.stop_name("Export RicePack…|push button|1,2"), "Export RicePack…")
        self.assertEqual(gk.stop_name("|spin button|3,4"), "")


if __name__ == "__main__":
    unittest.main()
