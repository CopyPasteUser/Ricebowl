"""Keep RiceBowl's clearly qualified engineering-evidence index auditable.

This is not a release gate. The actual seven SG acceptances remain governed
by issue #417; the matrix merely records which *defined* sub-checkpoints have
linked code or historical CI evidence.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


MATRIX = Path(__file__).resolve().parents[1] / "docs/sg1-sg7-evidence-progress.md"


class SGProgressEvidenceTests(unittest.TestCase):
    def test_all_seven_gates_have_four_explicit_boolean_checkpoints(self):
        text = MATRIX.read_text(encoding="utf-8")
        headings = list(re.finditer(r"(?m)^### (SG[1-7]) — ", text))
        self.assertEqual([match.group(1) for match in headings],
                         [f"SG{i}" for i in range(1, 8)])
        checked = 0
        for index, match in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            part = text[match.end():end]
            entries = re.findall(r"(?m)^- \[([x ])\] (.+)$", part)
            self.assertEqual(len(entries), 4, match.group(1))
            for value, description in entries:
                self.assertGreater(len(description), 30)
                if value == "x":
                    self.assertIn("](", description,
                                  "checked checkpoint needs a concrete evidence/source link")
                checked += (value == "x")
        self.assertEqual(checked, 14)
        self.assertEqual((checked * 100) // (len(headings) * 4), 50)

    def test_mechanical_table_matches_checkpoint_counts_and_formal_progress_distinction(self):
        text = MATRIX.read_text(encoding="utf-8")
        self.assertIn("Formal SG acceptance: 0 / 7 = 0%", text)
        self.assertIn("Engineering evidence coverage: 14 / 28 = 50%", text)
        expected = (2, 2, 2, 2, 2, 3, 1)
        for n, count in enumerate(expected, 1):
            row = f"| SG{n} | {count} | 4 | {count * 25}% |"
            self.assertIn(row, text)
        self.assertIn("| **Total** | **14** | **28** | **50%** |", text)
        self.assertIn("not an official SG completion percentage", text)


if __name__ == "__main__":
    unittest.main()
