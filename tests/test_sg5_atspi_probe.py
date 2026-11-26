"""Unit-level SG5 public AT-SPI probe behavior without a live bus."""
from __future__ import annotations

import importlib.util
import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "smoke_riceplate_atspi_client.py"
placeholder = types.ModuleType("pyatspi")
placeholder.ROLE_ENTRY = 1
placeholder.STATE_FOCUSED = 2
placeholder.ROLE_PUSH_BUTTON = 3
placeholder.ROLE_MENU_ITEM = 4
placeholder.Registry = types.SimpleNamespace(getDesktop=lambda index: None)
with patch.dict(sys.modules, {"pyatspi": placeholder}):
    spec = importlib.util.spec_from_file_location("sg5_atspi_probe", SCRIPT)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    VISIBLE = {"text": "secret command", "caret": 14, "focused": True, "selections": []}

    def run_probe(self, args, states, *, default=None, diag_error=None):
        events = iter(states)
        tick = [0]

        def monotonic():
            tick[0] += 1
            return float(tick[0])

        def next_sample(_name):
            event = next(events, default)
            if isinstance(event, Exception):
                raise event
            return event

        def diagnostics():
            if diag_error is not None:
                raise diag_error

        out, err = io.StringIO(), io.StringIO()
        with (patch.object(probe, "sample", side_effect=next_sample),
              patch.object(probe, "diagnostic_inventory", side_effect=diagnostics),
              patch.object(probe.time, "monotonic", side_effect=monotonic),
              patch.object(probe.time, "sleep", return_value=None),
              patch.object(sys, "argv", ["probe.py", *args]),
              patch.object(sys, "stdout", out), patch.object(sys, "stderr", err)):
            result = probe.main()
        return result, out.getvalue(), err.getvalue()

    def test_transient_absence_never_passes_until_three_consecutive_misses(self):
        result, out, _ = self.run_probe(["--absent"],
            [None, None, self.VISIBLE, None, None, None], default=self.VISIBLE)
        self.assertEqual(result, 0)
        self.assertEqual(out.count("PASS:"), 1)

    def test_interleaved_visible_node_prevents_false_dismissal(self):
        result, out, err = self.run_probe(["--absent"],
            [None, self.VISIBLE, None, self.VISIBLE, None, self.VISIBLE], default=self.VISIBLE)
        self.assertEqual(result, 1)
        self.assertNotIn("PASS", out)
        self.assertIn("still present", err)
        self.assertNotIn(self.VISIBLE["text"], err)

    def test_provider_error_resets_absence_confirmation(self):
        result, out, _ = self.run_probe(["--absent"],
            [None, RuntimeError("temporary provider error"), None, None, None], default=self.VISIBLE)
        self.assertEqual(result, 0)
        self.assertIn("PASS", out)

    def test_failed_diagnostics_return_clean_failure_without_content_leak(self):
        result, out, err = self.run_probe(["--absent"], [self.VISIBLE],
            default=self.VISIBLE, diag_error=RuntimeError("internal secret"))
        self.assertEqual(result, 1)
        self.assertEqual(out, "")
        self.assertIn("AT-SPI diagnostic unavailable: RuntimeError", err)
        self.assertNotIn("internal secret", err)
        self.assertNotIn(self.VISIBLE["text"], err)

    def test_absence_is_not_proven_by_incomplete_accessibility_tree(self):
        class Node:
            def __init__(self, children=(), *, broken=False):
                self.children = children
                self.broken = broken
                self.name = "inert"
            def getRole(self):
                if self.broken:
                    raise RuntimeError("provider changed while traversing")
                return 0
            @property
            def childCount(self):
                return len(self.children)
            def getChildAtIndex(self, index):
                return self.children[index]

        broken_tree = Node([Node(broken=True)])
        complete_tree = Node([Node()])
        with patch.object(probe.pyatspi.Registry, "getDesktop", return_value=broken_tree):
            with self.assertRaisesRegex(RuntimeError, "traversal incomplete"):
                probe.run_entry("Command")
        with patch.object(probe.pyatspi.Registry, "getDesktop", return_value=complete_tree):
            self.assertIsNone(probe.run_entry("Command"))

    def test_empty_atspi_registry_does_not_pass_absence(self):
        class EmptyDesktop:
            childCount = 0
        with patch.object(probe.pyatspi.Registry, "getDesktop", return_value=EmptyDesktop()):
            with self.assertRaisesRegex(RuntimeError, "no accessible applications"):
                probe.run_entry("Command")

    def test_missing_desktop_provider_fails_cleanly(self):
        with patch.object(probe.pyatspi.Registry, "getDesktop", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "desktop provider unavailable"):
                probe.run_entry("Command")
            with self.assertRaisesRegex(RuntimeError, "desktop provider unavailable"):
                probe.diagnostic_inventory()

    def test_unreadable_desktop_metadata_is_not_a_dismissal(self):
        class BrokenDesktop:
            @property
            def childCount(self):
                raise AttributeError("internal provider text")
        with patch.object(probe.pyatspi.Registry, "getDesktop", return_value=BrokenDesktop()):
            with self.assertRaisesRegex(RuntimeError, "desktop metadata unavailable"):
                probe.run_entry("Command")
            with self.assertRaisesRegex(RuntimeError, "desktop metadata unavailable"):
                probe.diagnostic_inventory()

    def test_invalid_desktop_child_count_fails_cleanly(self):
        class InvalidDesktop:
            childCount = None
        with patch.object(probe.pyatspi.Registry, "getDesktop", return_value=InvalidDesktop()):
            with self.assertRaisesRegex(RuntimeError, "no accessible applications"):
                probe.run_entry("Command")

    def test_truncated_accessibility_tree_is_not_an_absence_receipt(self):
        class Node:
            name = "inert"
            def __init__(self, count):
                self.childCount = count
            def getRole(self):
                return 0
            def getChildAtIndex(self, index):
                return Node(0)

        with patch.object(probe.pyatspi.Registry, "getDesktop", return_value=Node(201)):
            with self.assertRaisesRegex(RuntimeError, "traversal incomplete"):
                probe.run_entry("Command")
        root = Node(1)
        with patch.object(probe.pyatspi.Registry, "getDesktop", return_value=root):
            self.assertIsNone(probe.run_entry("Command"))

    def test_normal_live_text_probe_is_unchanged(self):
        state = {"text": "日本語", "caret": 3, "focused": True, "selections": []}
        result, out, err = self.run_probe(["--text", "日本語", "--caret", "3"], [state])
        self.assertEqual(result, 0)
        self.assertIn("PASS", out)
        self.assertEqual(err, "")

    def run_action(self, args, node, *, find_error=None):
        tick = [0]

        def monotonic():
            tick[0] += 1
            return float(tick[0])

        def finder(role, label):
            if find_error is not None:
                raise find_error
            return node

        out, err = io.StringIO(), io.StringIO()
        with (patch.object(probe, "find_node", side_effect=finder),
              patch.object(probe.time, "monotonic", side_effect=monotonic),
              patch.object(probe.time, "sleep", return_value=None),
              patch.object(sys, "argv", ["probe.py", *args]),
              patch.object(sys, "stdout", out), patch.object(sys, "stderr", err)):
            result = probe.main()
        return result, out.getvalue(), err.getvalue()

    class Action:
        def __init__(self, count=1, accepted=True):
            self.nActions, self.accepted, self.calls = count, accepted, []

        def doAction(self, index):
            self.calls.append(index)
            return self.accepted

    def node(self, action):
        return types.SimpleNamespace(queryAction=lambda: action)

    def test_do_action_invokes_public_action_zero_exactly_once(self):
        action = self.Action()
        result, out, _ = self.run_action(["--do-action", "OK"], self.node(action))
        self.assertEqual((result, action.calls), (0, [0]))
        self.assertIn("PASS: AT-SPI doAction", out)

    def test_do_action_fails_for_control_without_action_and_never_invokes(self):
        action = self.Action(count=0)
        result, out, err = self.run_action(
            ["--do-action", "Rename", "--role", "menu-item"], self.node(action))
        self.assertEqual((result, action.calls, out), (1, [], ""))
        self.assertIn("no AT-SPI action", err)

    def test_do_action_fails_when_action_refused_or_control_missing(self):
        refused = self.Action(accepted=False)
        result, out, err = self.run_action(["--do-action", "OK"], self.node(refused))
        self.assertEqual((result, out), (1, ""))
        self.assertIn("refused", err)
        result, out, err = self.run_action(["--do-action", "OK"], None)
        self.assertEqual((result, out), (1, ""))
        self.assertIn("no accessible button", err)
        result, _, err = self.run_action(["--do-action", "OK"], None,
                                         find_error=RuntimeError("secret"))
        self.assertEqual(result, 1)
        self.assertNotIn("secret", err)


if __name__ == "__main__":
    unittest.main()
