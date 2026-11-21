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
        self.assertEqual(checked, 15)
        self.assertEqual(round(checked * 100 / (len(headings) * 4), 1), 53.6)

    def test_mechanical_table_matches_checkpoint_counts_and_formal_progress_distinction(self):
        text = MATRIX.read_text(encoding="utf-8")
        self.assertIn("Formal SG acceptance: 1 / 7 ≈ 14.3%", text)
        self.assertIn("Engineering evidence coverage: 15 / 28 ≈ 53.6%", text)
        expected = (2, 2, 2, 2, 2, 4, 1)
        for n, count in enumerate(expected, 1):
            row = f"| SG{n} | {count} | 4 | {count * 25}% |"
            self.assertIn(row, text)
        self.assertIn("| **Total** | **15** | **28** | **53.6%** |", text)
        self.assertIn("not an official SG completion percentage", text)
        self.assertIn("Only SG6 is formally closed in #417", text)

    def test_sg6_acceptance_links_are_source_bound_and_hardware_scoped(self):
        text = MATRIX.read_text(encoding="utf-8")
        sg6 = text.split("### SG6 — ", 1)[1].split("### SG7 — ", 1)[0]
        self.assertIn("4 / 4 (software gate closed)", sg6)
        for evidence in (
            "344d5557a749213dfdd83be2db4a5ba21e8b2624",
            "44881618535",  # trusted-main tests
            "44881618473",  # installed Ubuntu/Mint recovery
            "44881618480",  # independent package builds and comparison
            "70471969",     # signed comparison report
            "70471973",     # signed four-deb manifest
        ):
            with self.subTest(evidence=evidence):
                self.assertIn(evidence, sg6)
        self.assertIn("not** third-party machine/toolchain or physical", sg6)


if __name__ == "__main__":
    unittest.main()
