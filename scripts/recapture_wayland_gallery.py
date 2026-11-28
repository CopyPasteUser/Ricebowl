#!/usr/bin/env python3
"""Re-publish existing native Wayland gallery names from a LOCAL smoke run.

Used after the original-artwork replacement (SG4): previews that show the old
wallpaper must come from a fresh real labwc/grim capture, never from drawing or
retouching. The only image operations are RGB conversion, an optional plain
LANCZOS downscale (target size differs from the source) and WebP encoding.

Usage: python3 scripts/recapture_wayland_gallery.py --source dist/riceplate-native-preview \
           --source-commit <40-hex> [--destination screenshots/wayland]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageStat

# Published preview -> native smoke PNG. Sizes are those of the existing previews.
CAPTURES = {
    "luna-live-1024.webp": "xp-luna-columns-menu-1024x768.png",
    "luna-live-fullhd.webp": "xp-luna-columns-menu-1920x1080.png",
    "luna-live-scale125.webp": "xp-luna-columns-menu-scale-125.png",
    "luna-pointer-closed.webp": "xp-luna-pointer-closed-1024x768.png",
    "luna-pointer-open.webp": "xp-luna-pointer-open-1024x768.png",
    "luna-pointer-find.webp": "xp-luna-pointer-find-1024x768.png",
    "luna-pointer-find-hover.webp": "xp-luna-pointer-find-hover-1024x768.png",
    "luna-pointer-find-paged.webp": "xp-luna-pointer-find-paged-1024x768.png",
    "luna-pointer-saved.webp": "xp-luna-pointer-saved-1024x768.png",
    "luna-saved-pinned-rightclick.webp": "xp-luna-pointer-saved-pinned-1024x768.png",
    "luna-saved-unpinned-rightclick.webp": "xp-luna-pointer-saved-unpinned-1024x768.png",
    "luna-window-chrome.webp": "xp-luna-window-chrome.png",
    "luna-window-default.webp": "xp-luna-window-default.png",
    "workspace.webp": "isolated-v5.png",
    "luna-desktop.webp": "xp-luna-columns.png",
    "luna-icons-after.webp": "xp-luna-columns.png",
    "luna-icons-before.webp": "xp-luna-default-icons.png",
    "luna-icons-menu.webp": "xp-luna-columns-menu.png",
    "luna-osd-default.webp": "xp-luna-columns-osd.png",
    "luna-osd-font.webp": "xp-luna-font-osd.png",
}
# Previews that are a plain crop of the 1366x768 frame (left, top, right, bottom).
CROPS = {
    "luna-osd-default.webp": (1010, 10, 1360, 150),
    "luna-osd-font.webp": (1010, 10, 1360, 150),
}
PROVENANCE = "recapture-20261128-provenance.json"
QUALITY = 83


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def recapture(source: Path, destination: Path, *, commit: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A full 40-character commit SHA is required")
    records = []
    with tempfile.TemporaryDirectory(prefix=".recapture-", dir=destination) as temporary:
        stage = Path(temporary)
        for target, name in CAPTURES.items():
            path = source / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Missing or unsafe source PNG: {name}")
            raw = path.read_bytes()
            if not (12_000 < len(raw) < 12_000_000 and raw.startswith(b"\x89PNG\r\n\x1a\n")):
                raise ValueError(f"Invalid PNG: {name}")
            with Image.open(destination / target) as existing:
                size = existing.size
            with Image.open(path) as screenshot:
                rgb = screenshot.convert("RGB")
            if target in CROPS:
                rgb = rgb.crop(CROPS[target])
            if max(ImageStat.Stat(rgb.resize((32, 18))).stddev) < 12:
                raise ValueError(f"Screenshot appears blank: {name}")
            resized = rgb.size != size
            if resized:
                if abs(rgb.width / rgb.height - size[0] / size[1]) > 0.01:
                    raise ValueError(f"Aspect ratio mismatch: {name} -> {target}")
                rgb = rgb.resize(size, Image.LANCZOS)
            rgb.save(stage / target, format="WEBP", quality=QUALITY, method=6)
            records.append({
                "preview": target, "source": name, "size": list(size),
                "downscaled": resized, "crop": list(CROPS[target]) if target in CROPS else None, "source_sha256": sha256(raw),
                "preview_sha256": sha256((stage / target).read_bytes()),
            })
        provenance = {
            "source_commit": commit,
            "environment": {"backend": "headless", "compositor": "labwc",
                            "native_surface": "riceplate", "renderer": "pixman"},
            "source": ("Local run of scripts/smoke_riceplate_native.sh, "
                       "scripts/smoke_luna_window_chrome.sh and `launcher.py de render`: "
                       "genuine headless labwc/grim compositor PNGs"),
            "reason": "replace previews that showed the pre-edff3f6 Luna wallpaper",
            "images": records,
        }
        (stage / PROVENANCE).write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for item in records:
            os.replace(stage / item["preview"], destination / item["preview"])
        os.replace(stage / PROVENANCE, destination / PROVENANCE)
    return provenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", default=Path("screenshots/wayland"), type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    result = recapture(args.source, args.destination, commit=args.source_commit)
    print(f"Recaptured {len(result['images'])} native screenshots from {result['source_commit']}")
