"""XP Start favorite and usage persistence is independent of taskbar pins."""

import json
import tempfile
import unittest
from pathlib import Path

from macrice.luna_start_state import (
    StartState, change_favorite, clear_recent_programs, load_start_state,
    record_launch, save_start_state,
)


class LunaStartStateTests(unittest.TestCase):
    def test_round_trip_and_intentional_no_favorites(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "winxp-start.json"
            self.assertIsNone(load_start_state(path).favorites)
            state = StartState((), {})
            save_start_state(state, path)
            self.assertEqual(load_start_state(path).favorites, ())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_tracking_successful_launches_is_bounded(self):
        state = StartState()
        record_launch(state, "firefox.desktop", now=100)
        record_launch(state, "firefox.desktop", now=150)
        record_launch(state, "fake name", now=200)
        self.assertEqual(state.launches, {"firefox.desktop": (2, 150)})
        for n in range(95):
            record_launch(state, f"app{n}.desktop", now=200 + n)
        self.assertLessEqual(len(state.launches), 80)
        self.assertNotIn("firefox.desktop", state.launches)

    def test_favorites_are_user_reorderable_and_separate(self):
        state = StartState()
        defaults = ("browser.desktop", "mail.desktop")
        self.assertTrue(change_favorite(state, "terminal.desktop", "pin", defaults))
        self.assertEqual(state.favorites, (*defaults, "terminal.desktop"))
        self.assertTrue(change_favorite(state, "terminal.desktop", "up"))
        self.assertEqual(state.favorites, ("browser.desktop", "terminal.desktop", "mail.desktop"))
        self.assertTrue(change_favorite(state, "browser.desktop", "unpin"))
        self.assertEqual(state.favorites, ("terminal.desktop", "mail.desktop"))
        self.assertFalse(change_favorite(state, "mail.desktop", "down"))

    def test_clear_recent_history_preserves_pins_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "winxp-start.json"
            state = StartState(("terminal.desktop",), {"browser.desktop": (4, 100)})
            self.assertTrue(clear_recent_programs(state))
            self.assertFalse(clear_recent_programs(state))
            save_start_state(state, file)
            self.assertEqual(load_start_state(file), StartState(("terminal.desktop",), {}))

    def test_refuses_symlink_and_malformed_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "actual.json"
            destination.write_text('{"schema": 1, "favorites": []}')
            link = root / "winxp-start.json"
            link.symlink_to(destination)
            with self.assertRaises(ValueError):
                load_start_state(link)
            with self.assertRaises(ValueError):
                save_start_state(StartState(), link)
            destination.write_text(json.dumps({"schema": 1,
                                               "launches": {"bad": [-2, 4]}}))
            with self.assertRaises(ValueError):
                load_start_state(destination)


    def test_malformed_json_types_are_rejected_without_mutating_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "winxp-start.json"
            invalid = (
                {"schema": 1, "favorites": "firefox.desktop"},
                {"schema": 1, "favorites": [42]},
                {"schema": 1, "favorites": {"a": "b"}},
                {"schema": 1, "launches": []},
                {"schema": 1, "launches": {"firefox.desktop": "1,2"}},
                {"schema": 1, "launches": {"firefox.desktop": [True, 10]}},
            )
            for payload in invalid:
                with self.subTest(payload=payload):
                    original = json.dumps(payload)
                    path.write_text(original)
                    with self.assertRaises(ValueError):
                        load_start_state(path)
                    self.assertEqual(path.read_text(), original)

    def test_clock_rollback_preserves_recent_order_and_caps_count(self):
        state = StartState()
        record_launch(state, "browser.desktop", now=300)
        record_launch(state, "browser.desktop", now=200)
        self.assertEqual(state.launches["browser.desktop"], (2, 300))
        record_launch(state, "mail.desktop", now=-10)
        self.assertEqual(state.launches["mail.desktop"], (1, 0))
        state.launches["browser.desktop"] = (1000000, 300)
        record_launch(state, "browser.desktop", now=301)
        self.assertEqual(state.launches["browser.desktop"], (1000000, 301))

    def test_invalid_in_memory_favorites_cannot_be_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "winxp-start.json"
            for favorites in ("browser.desktop", (None,), (123,)):
                with self.subTest(favorites=favorites):
                    with self.assertRaises(ValueError):
                        save_start_state(StartState(favorites, {}), path)
                    self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
