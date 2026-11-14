#!/usr/bin/env python3
"""Verify genuine Wayland screenshots show the classic RiceBowl taskbar.

The smoke compositor uses the classic schema-v1 recipe and no other desktop
background; comparing a pixel against its configured panel color detects
missing bars without synthetic image fixtures or visual-accuracy claims.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def validate(paths: list[Path]) -> None:
    if not 1 <= len(paths) <= 2:
        raise ValueError("Expected one or two genuine Wayland output captures")
    # `macrice/de/resources/recipes/classic.json`: background #203c59.
    expected = (0x20, 0x3C, 0x59)
    for path in paths:
        # Pillow's load() decodes pixels but can accept a PNG missing its
        # terminal IEND chunk. verify() checks the chunk stream and CRCs;
        # reopening is required because verify() invalidates the decoder.
        with Image.open(path) as image:
            if image.format != "PNG" or min(image.size) < 480:
                raise ValueError("Output screenshot has invalid PNG geometry")
            image.verify()
        with Image.open(path) as image:
            image.load()
            rgb = image.convert("RGB").getpixel((image.width // 2, image.height - 5))
        if any(abs(actual - base) > 6 for actual, base in zip(rgb, expected)):
            raise ValueError(f"No classic RiceBowl panel on output screenshot: {path.name} ({rgb})")


if __name__ == "__main__":
    validate([Path(argument) for argument in sys.argv[1:]])
    print("Verified real classic RiceBowl panel pixels on requested Wayland output(s)")
