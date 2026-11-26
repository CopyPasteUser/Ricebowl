"""Contract tests for the SG3/SG4 remainder smokes (no compositor needed).

The compositor receipts live in the shell/driver scripts under scripts/ (real labwc,
riceplate-native, GTK Creator, AT-SPI, grim). These tests keep the reusable pixel
checker honest (it must FAIL on a frame without the ellipsis) and keep the scripts
from silently losing the receipts they exist for.
"""
from __future__ import annotations

import importlib.util
import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_checker():
    spec = importlib.util.spec_from_file_location(
        "sg4_menu_ellipsis_check", SCRIPTS / "sg4_menu_ellipsis_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BACKGROUND, INK = (30, 40, 60), (240, 230, 200)
CELL, SCALE = 16, 2
# (first cell x, y, ellipsis cell index) relative to the menu origin (left=0, top=56)
LABELS = ((128, 56 + 108 + 13, 9), (8, 56 + 46 + 14, 4), (8, 56 + 46 + 44 + 14, 4))
ELLIPSIS = {(c, r) for c in (0, 3, 6) for r in (5, 6)}
LETTER = {(1, 2), (2, 2), (1, 3), (2, 3), (3, 4), (2, 5), (1, 6), (4, 1)}


def paint_cell(image, x, y, pixels, bold=True):
    for column, row in pixels:
        for dx in range(SCALE + (1 if bold and column < 7 else 0)):
            for dy in range(SCALE):
                image.putpixel((x + column * SCALE + dx, y + row * SCALE + dy), INK)


def frames(marker_pixels):
    base = Image.new("RGB", (1366, 768), (10, 10, 10))
    menu = base.copy()
    for x in range(0, 320):
        for y in range(56, 360):
            menu.putpixel((x, y), BACKGROUND)
    for x, y, cell in LABELS:
        paint_cell(menu, x + (cell - 1) * CELL, y, LETTER)
        paint_cell(menu, x + cell * CELL, y, marker_pixels)
    return base, menu


class EllipsisChecker(unittest.TestCase):
    def run_checker(self, marker):
        checker = load_checker()
        base, menu = frames(marker)
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory, "base.png"), Path(directory, "menu.png")
            base.save(first)
            menu.save(second)
            result = subprocess.run(
                [sys.executable, "-I", str(SCRIPTS / "sg4_menu_ellipsis_check.py"),
                 str(first), str(second), "56"], capture_output=True, text=True)
        self.assertIsNotNone(checker.lit_mask)
        return result

    def test_real_ellipsis_cells_pass(self):
        result = self.run_checker(ELLIPSIS)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(result.stdout.count("PASS"), 3)

    def test_a_silently_cut_label_fails(self):
        # The pre-fix behaviour: the last cell is just the next letter.
        result = self.run_checker(LETTER)
        self.assertEqual(result.returncode, 1)
        self.assertIn("is not the ellipsis", result.stderr)

    def test_a_question_mark_replacement_fails(self):
        question = {(2, 0), (3, 0), (4, 0), (5, 1), (4, 2), (3, 3), (3, 5)}
        self.assertEqual(self.run_checker(question).returncode, 1)

    def test_a_missing_menu_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            frame = Path(directory, "same.png")
            Image.new("RGB", (1366, 768), (10, 10, 10)).save(frame)
            result = subprocess.run(
                [sys.executable, "-I", str(SCRIPTS / "sg4_menu_ellipsis_check.py"),
                 str(frame), str(frame), "56"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no 320 px menu", result.stderr)


class SmokeContracts(unittest.TestCase):
    def test_python_drivers_compile(self):
        for name in ("sg4_creator_gui_roundtrip_driver.py", "sg3_click_target.py",
                     "sg4_menu_ellipsis_check.py", "smoke_sg3_ricepop_native_driver.py"):
            with self.subTest(name):
                ast.parse((SCRIPTS / name).read_text(encoding="utf-8"), filename=name)

    def test_shell_scripts_parse(self):
        for name in ("smoke_sg4_creator_gui_roundtrip_labwc.sh",
                     "smoke_sg3_ricepop_native_labwc.sh",
                     "smoke_sg4_imported_rices_labwc.sh"):
            with self.subTest(name):
                result = subprocess.run(["sh", "-n", str(SCRIPTS / name)],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_creator_gui_smoke_keeps_its_receipts(self):
        driver = (SCRIPTS / "sg4_creator_gui_roundtrip_driver.py").read_text()
        for needle in ("Export RicePack…", "Import RicePack…", "Review portable RicePack",
                       "Export reviewed bytes", "Import and edit",
                       "No session was changed", "1-garbage.ricepack", "2-truncated.ricepack",
                       "validates equal to the authored recipe", "Render preview",
                       "tree_digest", "closes=True"):
            self.assertIn(needle, driver)
        shell = (SCRIPTS / "smoke_sg4_creator_gui_roundtrip_labwc.sh").read_text()
        for needle in ("GDK_BACKEND=wayland", "wayland_pointer_click", "serverDecoration=\"no\"",
                       "exit 77", "id -u"):
            self.assertIn(needle, shell)

    def test_sg3_smoke_keeps_osd_receipts(self):
        driver = (SCRIPTS / "smoke_sg3_ricepop_native_driver.py").read_text()
        for needle in ("osd_announcement", "Announcement", "osd_brightness",
                       "XF86MonBrightnessUp", "osd_pointer_passthrough", "sg3_click_target.py"):
            self.assertIn(needle, driver)
        shell = (SCRIPTS / "smoke_sg3_ricepop_native_labwc.sh").read_text()
        for needle in ("RICEBOWL_BACKLIGHT_DIR", "brightnessctl"):
            self.assertIn(needle, shell)

    def test_orbit_smoke_requires_the_ellipsis_check_and_full_accessible_names(self):
        shell = (SCRIPTS / "smoke_sg4_imported_rices_labwc.sh").read_text()
        self.assertIn("sg4_menu_ellipsis_check.py", shell)
        self.assertIn('at_must has "push button" "Applications"', shell)


if __name__ == "__main__":
    unittest.main()
