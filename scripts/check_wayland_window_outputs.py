#!/usr/bin/env python3
"""Verify that a real Wayland application's task appeared and disappeared."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageChops


def changed_panel_pixels(before: Path, after: Path) -> int:
    """Count meaningful changes in the task-list area, excluding the clock/tray."""
    with Image.open(before) as initial, Image.open(after) as current:
        # The taskbar is at the bottom of the framebuffer, but decoding only
        # that crop does not prove the compositor supplied a complete image.
        # Reject truncated PNGs rather than accepting partial visual evidence.
        if initial.format != "PNG" or current.format != "PNG":
            raise ValueError("Wayland taskbar captures must be PNG")
        initial.load()
        current.load()
        if initial.size != current.size:
            raise ValueError("Wayland framebuffer sizes changed during the window test")
        width, height = initial.size
        if width < 640 or height < 160:
            raise ValueError("Wayland framebuffer too small for taskbar acceptance")
        bounds = (96, height - 36, min(width - 160, 700), height)
        diff = ImageChops.difference(
            initial.convert("RGB").crop(bounds), current.convert("RGB").crop(bounds)
        )
        pixels = diff.tobytes()
        return sum(1 for offset in range(0, len(pixels), 3)
                   if pixels[offset] + pixels[offset + 1] + pixels[offset + 2] > 80)


def validate(before: Path, opened: Path, closed: Path) -> tuple[int, int]:
    on = changed_panel_pixels(before, opened)
    off = changed_panel_pixels(before, closed)
    if on < 30:
        raise ValueError(f"real application did not visibly appear in taskbar: {on} pixels")
    if off > 12:
        raise ValueError(f"taskbar did not return to empty after application closed: {off} pixels")
    return on, off


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("opened", type=Path)
    parser.add_argument("closed", type=Path)
    args = parser.parse_args()
    opened_pixels, closed_pixels = validate(args.before, args.opened, args.closed)
    print(f"Real Wayland app taskbar: opened={opened_pixels} changed pixels, "
          f"after-close={closed_pixels} residual pixels")
