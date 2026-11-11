#!/usr/bin/env python3
"""Locate exactly one real native calendar popup across two Wayland outputs.

The smoke script supplies genuine grim PNG captures. The expected pixel comes
from the classic recipe's #4179aa calendar header; no mock screen is accepted.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def calendar_matches(paths: list[Path]) -> list[int]:
    if not 1 <= len(paths) <= 2:
        raise ValueError("Expected one or two native Wayland calendar screenshots")
    expected = (0x41, 0x79, 0xAA)
    found = []
    for index, path in enumerate(paths):
        with Image.open(path) as image:
            if image.format != "PNG" or min(image.size) < 480:
                raise ValueError("Invalid native calendar capture")
            # Validate the complete framebuffer before trusting a header pixel.\n            # Partial PNGs can retain the sampled calendar region while the\n            # remaining Wayland capture is corrupt or missing.\n            image.load()\n            x = image.width - 336 - 8 + 20
            y = image.height - 36 - 352 + 10
            rgb = image.convert("RGB").getpixel((x, y))
            if all(abs(actual - target) <= 2 for actual, target in zip(rgb, expected)):
                found.append(index)
    return found


def visible_calendar(paths: list[Path]) -> int:
    if len(paths) != 2:
        raise ValueError("Expected two native Wayland calendar screenshots")
    found = calendar_matches(paths)
    if len(found) != 1:
        raise ValueError(f"Expected exactly one output-bound calendar, found {len(found)}")
    return found[0]


if __name__ == "__main__":
    if sys.argv[1:2] == ["--closed"]:
        if len(sys.argv) != 3 or calendar_matches([Path(sys.argv[2])]):
            raise SystemExit("Calendar must remain closed after output reconnect")
    else:
        print(visible_calendar([Path(item) for item in sys.argv[1:]]))
