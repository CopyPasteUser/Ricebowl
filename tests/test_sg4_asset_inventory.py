"""WP4.5: the asset-rights inventory must cover every shipped asset and stay hash-exact.

Offline and fast.  Fails when an asset is added, removed or changed without
re-running ``python3 scripts/sg4_asset_inventory.py`` and re-reviewing
docs/sg4-asset-rights-audit.md.  It also pins that the audit never claims the
rights were independently verified (only the owner may flip that).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sg4_asset_inventory.py"
spec = importlib.util.spec_from_file_location("sg4_asset_inventory", SCRIPT)
inv = importlib.util.module_from_spec(spec)
sys.modules["sg4_asset_inventory"] = inv
spec.loader.exec_module(inv)

REGEN = "run `python3 scripts/sg4_asset_inventory.py`, then re-review docs/sg4-asset-rights-audit.md"
AUDIT = ROOT / "docs" / "sg4-asset-rights-audit.md"


class AssetInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(inv.INVENTORY.read_text(encoding="utf-8"))
        cls.by_path = {item["path"]: item for item in cls.data["assets"]}

    def test_every_shipped_asset_is_inventoried(self):
        actual = set(inv.discover(ROOT))
        listed = set(self.by_path)
        self.assertEqual(sorted(actual - listed), [], f"assets missing from inventory: {REGEN}")
        self.assertEqual(sorted(listed - actual), [], f"inventory lists deleted assets: {REGEN}")
        self.assertEqual(len(listed), len(self.data["assets"]), "duplicate inventory paths")

    def test_hashes_and_sizes_have_not_drifted(self):
        drift = []
        for rel, item in self.by_path.items():
            path = ROOT / rel
            if not path.is_file():
                continue  # reported by the coverage test
            if inv.sha256_file(path) != item["sha256"] or path.stat().st_size != item["size"]:
                drift.append(rel)
        self.assertEqual(drift, [], f"asset bytes changed since audit: {REGEN}")

    def test_entries_are_complete_and_flags_are_catalogued(self):
        catalogue = self.data["flag_catalogue"]
        self.assertEqual(set(catalogue), set(inv.FLAGS))
        for rel, item in self.by_path.items():
            for field in ("sha256", "declared_licence", "origin", "category"):
                self.assertTrue(item[field], f"{rel}: empty {field}")
            self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
            self.assertNotEqual(item["category"], "uncategorised", f"{rel}: classify it")
            self.assertLessEqual(set(item["flags"]), set(catalogue), rel)
        self.assertEqual(self.data["counts"]["total"], len(self.by_path))

    def test_rule_derived_fields_match_the_committed_inventory(self):
        fresh = {a["path"]: a for a in inv.build(ROOT, with_git=False)["assets"]}
        ignore = ("first_commit", "users")
        stale = [rel for rel, item in self.by_path.items()
                 if rel in fresh and {k: v for k, v in item.items() if k not in ignore}
                 != {k: v for k, v in fresh[rel].items() if k not in ignore}]
        self.assertEqual(stale, [], f"classification or flags changed: {REGEN}")

    def test_audit_never_claims_independent_verification(self):
        self.assertEqual(self.data["audit_status"], "prepared-awaiting-owner-signoff")
        self.assertNotIn("rights_independently_verified", self.data)
        for rel in ("macrice/de/pack.py", "macrice/de/creator_release.py"):
            source = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotRegex(source, r'"rights_independently_verified"\s*:\s*True', rel)
            self.assertRegex(source, r'"rights_independently_verified"\s*:\s*False', rel)
        doc = AUDIT.read_text(encoding="utf-8")
        self.assertIn("rights_independently_verified", doc)
        self.assertNotRegex(doc, r"(?i)rights_independently_verified\W{0,4}(?:=|:|is|now)\s*true")

    def test_flags_and_high_severity_assets_are_discussed_in_the_audit(self):
        doc = AUDIT.read_text(encoding="utf-8")
        for flag in self.data["flag_catalogue"]:
            self.assertIn(flag, doc, f"{flag} missing from audit document")
        high = sorted({rel for rel, item in self.by_path.items() for f in item["flags"]
                       if self.data["flag_catalogue"][f]["severity"] == "high"})
        for rel in high:
            self.assertIn(rel, doc, f"high-severity asset {rel} not discussed in audit")


if __name__ == "__main__":
    unittest.main()
