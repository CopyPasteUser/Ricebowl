#!/usr/bin/env python3
"""Prove a native schema-v5 menu is visible on exactly one Wayland output."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def menu_matches(paths: list[Path]) -> list[int]:
    if not 1 <= len(paths) <= 2:
        raise ValueError("Expected one or two native menu captures")
    found = []
    for index, path in enumerate(paths):
        with Image.open(path) as image:
            if image.format != "PNG" or min(image.size) < 480:
                raise ValueError("Invalid Wayland menu capture")
            # Decode the entire framebuffer, not just the sampled header pixel.
            # A truncated CI capture can retain its first scanlines and otherwise
            # incorrectly pass this one-pixel visibility assertion.
            image.load()
            # Schema-v5 test recipe is top-aligned with a 40 px panel.
            # The native menu's 38 px header is #4179aa.
            rgb = image.convert("RGB").getpixel((20, 40 + 10))
            if all(abs(actual - target) <= 2 for actual, target in
                   zip(rgb, (0x41, 0x79, 0xAA))):
                found.append(index)
    return found


def active_menu_output(paths: list[Path]) -> int:
    if len(paths) != 2:
        raise ValueError("Expected two native menu captures")
    indexes = menu_matches(paths)
    if len(indexes) != 1:
        raise ValueError(f"Expected exactly one output-owned menu, found {len(indexes)}")
    return indexes[0]


if __name__ == "__main__":
    if sys.argv[1:2] == ["--closed"]:
        if len(sys.argv) != 3 or menu_matches([Path(sys.argv[2])]):
            raise SystemExit("Native menu must stay closed after output reconnect")
    else:
        print(active_menu_output([Path(item) for item in sys.argv[1:]]))
