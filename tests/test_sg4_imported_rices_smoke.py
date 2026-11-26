"""SG4 WP4.3: contract tests for the imported-rices interactive compositor smoke.

The compositor receipts run in `scripts/smoke_sg4_imported_rices_labwc.sh` (real
labwc + riceplate-native + AT-SPI; needs the release binaries). These tests run
anywhere: they execute the REAL Creator -> RicePack export -> import helper in a
disposable XDG profile (no compositor needed) and keep the smoke's structure and
workflow wiring from eroding.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts/smoke_sg4_imported_rices_labwc.sh"
SETUP = ROOT / "scripts/sg4_imported_rices_setup.py"
PROBE = ROOT / "scripts/sg4_atspi_probe.py"
WORKFLOW = ROOT / ".github/workflows/riceplate-native.yml"


@unittest.skipIf(os.geteuid() == 0, "RiceBowl Creator refuses to run as root")
class ImportedRicesSetup(unittest.TestCase):
    def run_helper(self, mode, folder, config, state, home):
        env = dict(os.environ, XDG_CONFIG_HOME=str(config), XDG_STATE_HOME=str(state),
                   HOME=str(home))
        result = subprocess.run([sys.executable, "-I", str(SETUP), mode, str(folder)],
                                capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_author_export_then_fresh_profile_import_installs_two_distinct_rices(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            dirs = {name: base / name for name in (
                "a-config", "a-state", "i-config", "i-state", "home", "packs")}
            for path in dirs.values():
                path.mkdir(mode=0o700)
            authored = self.run_helper("author", dirs["packs"], dirs["a-config"],
                                       dirs["a-state"], dirs["home"])
            self.assertEqual([p["template"] for p in authored["packs"]],
                             ["heritage-composer", "orbit-composer"])
            self.assertEqual(len({p["semantic_sha256"] for p in authored["packs"]}), 2)
            # The importing profile has never seen the author's drafts.
            self.assertFalse((dirs["i-config"] / "ricebowl").exists())
            imported = self.run_helper("import", dirs["packs"], dirs["i-config"],
                                       dirs["i-state"], dirs["home"])
            rices = imported["rices"]
            self.assertEqual([r["template"] for r in rices],
                             ["heritage-composer", "orbit-composer"])
            self.assertEqual([r["semantic_sha256"] for r in rices],
                             [p["semantic_sha256"] for p in authored["packs"]])
            self.assertEqual([(r["position"], r["menu_presentation"]) for r in rices],
                             [("bottom", "tabs"), ("top", "sidebar")])
            for rice in rices:
                recipe = Path(rice["recipe_path"])
                self.assertTrue(recipe.is_file())
                self.assertTrue(str(recipe).startswith(str(dirs["i-config"])))
                self.assertEqual(stat.S_IMODE(recipe.stat().st_mode) & 0o077, 0)
            # Importing never selects or applies anything: no selection file.
            self.assertFalse(list((dirs["i-config"] / "ricebowl").rglob(".active-recipe")))

    def test_import_helper_refuses_a_missing_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name in ("config", "state", "home", "packs"):
                (base / name).mkdir(mode=0o700)
            env = dict(os.environ, XDG_CONFIG_HOME=str(base / "config"),
                       XDG_STATE_HOME=str(base / "state"), HOME=str(base / "home"))
            result = subprocess.run([sys.executable, "-I", str(SETUP), "import",
                                     str(base / "packs")],
                                    capture_output=True, text=True, env=env, timeout=60)
            self.assertNotEqual(result.returncode, 0)


class SmokeContract(unittest.TestCase):
    def test_posix_syntax_and_python_helpers_compile(self):
        self.assertEqual(subprocess.run(["sh", "-n", str(SMOKE)]).returncode, 0)
        for path in (SETUP, PROBE):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_both_stages_and_both_imported_rices_are_exercised(self):
        text = SMOKE.read_text(encoding="utf-8")
        for needle in ("stage_apply", "stage_input", "creator-live-apply",
                       "creator-live-restore", "heritage-composer", "orbit-composer",
                       "RICEBOWL_DE_SCREEN_READER=1", "labwc --exit",
                       'at_must noaction "push button" "Wi-Fi, N/A, unavailable"',
                       "Log out of RiceBowl, unavailable",
                       "Command: Could not run", "Wi-Fi, On, failed",
                       "set_mode 640 480", "profile_digest"):
            self.assertIn(needle, text, needle)

    def test_smoke_never_reaches_a_real_session_or_provider(self):
        text = SMOKE.read_text(encoding="utf-8")
        # Only logging shims may be on the shell's PATH; no real fuzzel/foot.
        self.assertIn('PATH="$bin" RICEBOWL_DE_NESTED=0', text)
        self.assertNotRegex(text, r"(?m)^\s*(sudo|systemctl|loginctl)\b")

    def test_workflow_path_filter_syntax_check_and_run_step(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertGreaterEqual(
            len(re.findall(r"'scripts/smoke_sg4_imported_rices_labwc\.sh'", workflow)), 2,
            "both pull_request and push path filters")
        for helper in ("sg4_imported_rices_setup.py", "sg4_atspi_probe.py"):
            self.assertGreaterEqual(workflow.count(f"'scripts/{helper}'"), 2, helper)
        self.assertIn("sh -n scripts/smoke_sg4_imported_rices_labwc.sh", workflow)
        self.assertRegex(workflow, r"timeout -k 5s \d+s sh scripts/smoke_sg4_imported_rices_labwc\.sh")


if __name__ == "__main__":
    unittest.main()
