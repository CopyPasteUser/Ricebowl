"""SG2 WP2.4 / SG4 WP4.2: contract tests for the real-labwc GUI smokes.

The compositor receipts run in `scripts/smoke_sg2_settings_gui_labwc.sh` and
`scripts/smoke_sg4_creator_gui_roundtrip_labwc.sh` (real labwc + AT-SPI + grim). These
tests run anywhere: they keep the smokes' page coverage, structure and workflow wiring
from eroding, and check the fixture's fake-provider reuse.
"""
from __future__ import annotations

import ast
import re
import subprocess
import unittest
from pathlib import Path

from macrice.de import settings

ROOT = Path(__file__).resolve().parents[1]
SG2_SMOKE = ROOT / "scripts/smoke_sg2_settings_gui_labwc.sh"
SG2_DRIVER = ROOT / "scripts/sg2_settings_gui_driver.py"
SG4_SMOKE = ROOT / "scripts/smoke_sg4_creator_gui_roundtrip_labwc.sh"
SG4_DRIVER = ROOT / "scripts/sg4_creator_gui_roundtrip_driver.py"
SG4_LOGIN = ROOT / "scripts/smoke_sg4_creator_full_login_labwc.sh"
GTK_KEYBOARD = ROOT / "scripts/gtk_keyboard.py"
LOGIN_SCRIPT = ROOT / "packaging/wayland/ricebowl-wayland-session"
WORKFLOW = ROOT / ".github/workflows/riceplate-native.yml"


def _pages_table() -> dict:
    tree = ast.parse(SG2_DRIVER.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "PAGES":
            # The table is plain data built from dict(...) calls; nothing else is evaluated.
            return eval(compile(ast.Expression(node.value), str(SG2_DRIVER), "eval"),
                        {"__builtins__": {}, "dict": dict})
    raise AssertionError("PAGES table missing")


class SettingsGuiSmokeContract(unittest.TestCase):
    def test_posix_syntax_and_drivers_compile(self):
        for smoke in (SG2_SMOKE, SG4_SMOKE, SG4_LOGIN):
            self.assertEqual(subprocess.run(["sh", "-n", str(smoke)]).returncode, 0, smoke)
        for driver in (SG2_DRIVER, SG4_DRIVER, GTK_KEYBOARD):
            compile(driver.read_text(encoding="utf-8"), str(driver), "exec")

    def test_every_riceSpice_page_is_in_the_smoke_with_all_states(self):
        table = _pages_table()
        pages = {key for key, _title, _desc in settings.LUNA_SECTIONS} | \
                {key for key, _title, _desc in settings.SECTIONS}
        self.assertEqual(set(table), pages,
                         "a RiceSpice page was added or removed: update the GUI smoke")
        for page, spec in table.items():
            for key in ("control", "typed", "base", "unavail", "absent"):
                self.assertIn(key, spec, (page, key))
            self.assertTrue(spec["base"] and spec["unavail"] and spec["control"], page)
        self.assertEqual([page for page, spec in table.items() if spec.get("luna")], ["taskbar"],
                         "only the Luna-only page runs as the Luna window")

    def test_denied_busy_and_unavailable_texts_are_the_products_own(self):
        driver = SG2_DRIVER.read_text(encoding="utf-8")
        self.assertEqual(settings.WORKING_TEXT, "Working with system services…")
        for needle in ('WORKING = "Working with system services…"',
                       'REFUSED = "System request in progress; retry this action when it finishes."',
                       "FakeAdapters", "FakePreferences", "SG2G_CLICKER",
                       "visible=False", "pairwise-different"):
            self.assertTrue(needle in driver, needle)
        self.assertIn("wayland_pointer_click", SG2_SMOKE.read_text(encoding="utf-8"))
        from macrice import authorization
        self.assertIn(authorization.DENIED_MESSAGE, driver)

    def test_smoke_uses_a_disposable_profile_and_no_real_provider(self):
        text = SG2_SMOKE.read_text(encoding="utf-8")
        self.assertIn("mktemp -d", text)
        self.assertIn('XDG_CONFIG_HOME="$runtime/config"', text)
        self.assertNotRegex(text, r"(?m)^\s*(sudo|systemctl|loginctl|nmcli|bluetoothctl)\b")

    def test_creator_smoke_runs_the_apply_stage_against_a_real_supervised_session(self):
        text = SG4_SMOKE.read_text(encoding="utf-8")
        for needle in ("de start --nested --panel native", "ricebowl-live-wayland-0.sock",
                       "labwc --exit", "1366x768", "windowRule"):
            self.assertTrue(needle in text, needle)
        driver = SG4_DRIVER.read_text(encoding="utf-8")
        for needle in ("Install saved version…", "Apply in Wayland…", "Restore previous rice…",
                       "Live change cancelled. Desktop unchanged.",
                       "Live change not confirmed", "Live change unavailable: ",
                       "desktop=True"):
            self.assertTrue(needle in driver, needle)

    def test_gtk_keyboard_stages_use_the_shared_padded_real_keys(self):
        """The keyboard receipts (WP4.2/2.4) must keep using real wtype keys through the one helper."""
        for driver in (SG2_DRIVER, SG4_DRIVER):
            text = driver.read_text(encoding="utf-8")
            self.assertIn("import gtk_keyboard", text, driver.name)
            self.assertNotIn("wtype(", text, driver.name + ": raw wtype instead of gtk_keyboard.gtk_key")
            self.assertIn("unpadded_key", text, driver.name + ": the negative control that pins the cause")
        sg2 = SG2_DRIVER.read_text(encoding="utf-8")
        for needle in ("KEYBOARD_PAGES", "def keyboard_taskbar", "exactly one call",
                       'SG2G_ONLY'):
            self.assertIn(needle, sg2, needle)
        sg4 = SG4_DRIVER.read_text(encoding="utf-8")
        for needle in ("def keyboard_stage", "Escape", "I reviewed the package contents", "Export reviewed bytes",
                       "wrap to", "TEMPLATE_BUTTONS", "SIDEBAR_BUTTONS"):
            self.assertIn(needle, sg4, needle)
        shell = SG4_SMOKE.read_text(encoding="utf-8")
        self.assertIn('"$driver" keyboard', shell)
        self.assertIn("keys", shell)

    def test_the_driver_scripts_do_not_keep_private_copies_of_the_pad_key(self):
        for script in ROOT.joinpath("scripts").glob("*.py"):
            if script.name == "gtk_keyboard.py":
                continue
            self.assertNotIn('"F35"', script.read_text(encoding="utf-8"),
                             script.name + " must take the pad key from scripts/gtk_keyboard.py")

    def test_full_login_smoke_runs_the_packaged_login_script_not_nested(self):
        text = SG4_LOGIN.read_text(encoding="utf-8")
        self.assertIn('packaging/wayland/ricebowl-wayland-session" --native', text)
        code = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
        self.assertFalse([line for line in code if "--nested" in line or "RICEBOWL_DE_NESTED=1" in line],
                         "the full-login smoke must not start a nested session")
        for needle in ("WLR_BACKENDS=headless", "unset WAYLAND_DISPLAY DISPLAY", "roundtrip persist relogin",
                       ".local/bin/ricebowl", "windowRule", "exit 77", "id -u"):
            self.assertIn(needle, text, needle)
        # the login entry is the packaged file, and it is what the .desktop file executes
        self.assertIn('exec "$app" de start --panel native', LOGIN_SCRIPT.read_text(encoding="utf-8"))
        desktop = (ROOT / "packaging/wayland/ricebowl-native.desktop").read_text(encoding="utf-8")
        self.assertIn("Exec=/usr/bin/ricebowl-wayland-session --native", desktop)
        driver = SG4_DRIVER.read_text(encoding="utf-8")
        for needle in ("RICEBOWL_DM_SESSION", 'RICEBOWL_DE_NESTED") == "0"', "next_login_persisted",
                       "The choice also persists for the next login.", "labwc", "--exit",
                       "def residue_check", "login_relogin", "def login_persist"):
            self.assertIn(needle, driver, needle)

    def test_workflow_wiring(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        for script in ("smoke_sg2_settings_gui_labwc.sh", "sg2_settings_gui_driver.py",
                       "smoke_sg4_creator_gui_roundtrip_labwc.sh",
                       "sg4_creator_gui_roundtrip_driver.py", "macrice/de/settings.py"):
            self.assertGreaterEqual(len(re.findall(re.escape(script) + "'", workflow)), 2,
                                    f"{script}: both pull_request and push path filters")
        for script in ("smoke_sg4_creator_full_login_labwc.sh", "gtk_keyboard.py"):
            self.assertGreaterEqual(len(re.findall(re.escape("scripts/" + script) + "'", workflow)), 2,
                                    f"{script}: both pull_request and push path filters")
        self.assertIn("py_compile scripts/gtk_keyboard.py", workflow)
        self.assertIn("sh -n scripts/smoke_sg4_creator_full_login_labwc.sh", workflow)
        self.assertRegex(workflow,
                         r"timeout -k 5s \d+s sh scripts/smoke_sg4_creator_full_login_labwc\.sh")
        for check in ("sh -n scripts/smoke_sg2_settings_gui_labwc.sh",
                      "py_compile scripts/sg2_settings_gui_driver.py",
                      "sh -n scripts/smoke_sg4_creator_gui_roundtrip_labwc.sh",
                      "py_compile scripts/sg4_creator_gui_roundtrip_driver.py"):
            self.assertTrue(check in workflow, check)
        self.assertRegex(workflow, r"timeout -k 5s \d+s sh scripts/smoke_sg2_settings_gui_labwc\.sh")
        self.assertRegex(workflow,
                         r"timeout -k 5s \d+s sh scripts/smoke_sg4_creator_gui_roundtrip_labwc\.sh")


if __name__ == "__main__":
    unittest.main()
