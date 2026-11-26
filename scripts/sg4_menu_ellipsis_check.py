#!/usr/bin/env python3
"""Pixel receipt: overflowing native-menu labels end in a real ellipsis.

  sg4_menu_ellipsis_check.py BASE.png MENU.png MENU_TOP_Y

BASE/MENU are real `grim` frames of the output without/with the Orbit Composer
launcher menu open (sidebar presentation, `font_scale` 2, fixed 320 px menu).
The menu's left edge is recovered from the pixels that changed. At scale 2 the
sidebar rows have room for ten cells ("Applications" -> "Applicati…") and the
group rows for five ("Explore" -> "Expl…", "Session" -> "Sess…"). The last cell of each overflowing label must hold the shared
bitmap ellipsis (three 1x2 dots at cell columns 0/3/6, rows 5/6, doubled by the
font scale) on an otherwise empty cell; the cell before it must not.
Exit 0 = every receipt holds; the failure message names the cell.
"""
from __future__ import annotations

import sys

from PIL import Image, ImageChops

SCALE = 2
CELL = 8 * SCALE
# native_menu.rs: SIDEBAR_WIDTH 112, TAB_TOP 46, SIDEBAR_ROW_HEIGHT 44,
# ACTION_TOP 108, ACTION_HEIGHT 42; labels are vertically centred in a row.
DOT_COLUMNS, DOT_ROWS = (0, 3, 6), (5, 6)


def lit_mask(image, x, y):
    """Set of (column, row) font pixels that differ from the cell background."""
    background = image.getpixel((x + 1, y + 1))
    lit = set()
    for row in range(8):
        for column in range(8):
            # Sample the right-hand sub-pixel column of each font pixel: the
            # bold face widens a pixel by one px into its right neighbour,
            # which only ever overwrites the neighbour's LEFT sub-pixel.
            top = image.getpixel((x + column * SCALE + 1, y + row * SCALE))
            bottom = image.getpixel((x + column * SCALE + 1, y + row * SCALE + 1))
            states = {max(abs(a - b) for a, b in zip(c, background)) > 60
                      for c in (top, bottom)}
            if len(states) != 1:
                raise SystemExit(f"FAIL: half-lit font pixel at cell ({x},{y})")
            if states == {True}:
                lit.add((column, row))
    return lit


def main() -> int:
    base, menu, top = sys.argv[1], sys.argv[2], int(sys.argv[3])
    with Image.open(base) as a, Image.open(menu) as b:
        a, b = a.convert("RGB"), b.convert("RGB")
        box = ImageChops.difference(a, b).crop((0, top, a.width, a.height)) \
            .point(lambda v: 255 if v > 20 else 0).convert("L").getbbox()
        if box is None or box[2] - box[0] < 300:
            print(f"FAIL: no 320 px menu found in the frame (bbox {box})", file=sys.stderr)
            return 1
        left = box[0]
        expected = {(c, r) for c in DOT_COLUMNS for r in DOT_ROWS}
        checks = [
            # (label, first cell x, y, index of the cell that must be the ellipsis)
            ("Applications row", left + 112 + 4 + 12, top + 108 + (42 - 16) // 2, 9),
            ("Explore group", left + 8, top + 46 + (44 - 16) // 2, 4),
            ("Session group", left + 8, top + 46 + 44 + (44 - 16) // 2, 4),
        ]
        for name, x, y, cell in checks:
            marker = lit_mask(b, x + cell * CELL, y)
            if marker != expected:
                print(f"FAIL: {name}: cell {cell} is not the ellipsis "
                      f"(lit font pixels {sorted(marker)})", file=sys.stderr)
                return 1
            before = lit_mask(b, x + (cell - 1) * CELL, y)
            if not before or before == expected:
                print(f"FAIL: {name}: cell {cell - 1} should hold a letter, "
                      f"saw {sorted(before)}", file=sys.stderr)
                return 1
            print(f"PASS: {name}: cell {cell} is the ellipsis, cell {cell - 1} a letter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
