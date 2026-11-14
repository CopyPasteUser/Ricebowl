#!/usr/bin/env python3
"""Publish verified *real* native labwc XDG file-desktop captures.

Input is produced by the end-to-end compositor smoke test, never by PIL drawing
or a synthetic UI. WebP encoding is the only image transformation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageChops, ImageStat

CAPTURES = {
    "luna-file-desktop-before-20261114.webp": "xdg-before.png",
    "luna-file-desktop-live-20261114.webp": "xdg-created.png",
    "luna-file-desktop-selected-20261114.webp": "xdg-selected.png",
    "luna-file-desktop-folder-20261114.webp": "xdg-folder.png",
}
PROVENANCE = "luna-file-desktop-provenance-20261114.json"
SIZE = (1366, 768)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def count_changed(first: Image.Image, second: Image.Image) -> int:
    # Only the actual desktop icon region: ignore clock changes and taskbar.
    roi = (0, 0, 900, 700)
    delta = ImageChops.difference(first.crop(roi), second.crop(roi))
    return sum(max(pixel) > 20 for pixel in delta.getdata())


def publish(source: Path, destination: Path, *, commit: str, run_id: int) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or run_id <= 0:
        raise ValueError("Full commit SHA and positive Actions run ID required")
    if not source.is_dir() or source.is_symlink() or not destination.is_dir():
        raise ValueError("Expected existing source and gallery directories")
    if destination.is_symlink():
        raise ValueError("Gallery destination must not be a symlink")
    # Fail closed rather than silently overwrite an unrelated gallery revision.
    if any((destination / name).exists() or (destination / name).is_symlink()
           for name in (*CAPTURES.keys(), PROVENANCE)):
        raise ValueError("Target gallery already contains this dated publication")
    verified = {}
    records = []
    for target, filename in CAPTURES.items():
        path = source / filename
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing genuine compositor PNG: {filename}")
        raw = path.read_bytes()
        if not (12_000 < len(raw) < 12_000_000 and raw.startswith(b"\x89PNG\r\n\x1a\n")):
            raise ValueError(f"Invalid source PNG: {filename}")
        with Image.open(path) as opened:
            opened.load()
            if opened.format != "PNG" or opened.size != SIZE:
                raise ValueError(f"Wrong source screenshot type/geometry: {filename}")
            img = opened.convert("RGB")
            if max(ImageStat.Stat(img.resize((32, 18))).stddev) < 12:
                raise ValueError(f"Frame is visually blank: {filename}")
            verified[filename] = img
        records.append({
            "preview": target, "source": filename, "size": list(SIZE),
            "source_sha256": sha256(raw),
        })
    changes = {
        "inotify_created": count_changed(verified["xdg-before.png"], verified["xdg-created.png"]),
        "real_selection": count_changed(verified["xdg-created.png"], verified["xdg-selected.png"]),
        "new_folder": count_changed(verified["xdg-selected.png"], verified["xdg-folder.png"]),
    }
    if any(pixels <= 60 for pixels in changes.values()):
        raise ValueError(f"Desktop changes were not rendered in actual frames: {changes}")
    with tempfile.TemporaryDirectory(prefix=".ricebowl-xdg-gallery-", dir=destination) as temporary:
        stage = Path(temporary)
        for record in records:
            img = verified[record["source"]]
            target = stage / record["preview"]
            img.save(target, format="WEBP", quality=83, method=6)
            with Image.open(target) as reopened:
                reopened.load()
                if reopened.format != "WEBP" or reopened.size != SIZE:
                    raise ValueError("WebP validation failed")
            record["preview_sha256"] = sha256(target.read_bytes())
        receipt = {
            "ci_run": run_id,
            "source_commit": commit,
            "source": "genuine labwc headless compositor grim frames from full XDG file-desktop smoke",
            "environment": {"compositor": "labwc", "backend": "headless",
                            "renderer": "pixman", "native_surface": "riceplate"},
            "image_changes": changes,
            "limitations": ("RiceField open is tested as exact argv with an isolated mock; "
                            "no actual RiceField window is shown. No physical GPU/keyboard acceptance."),
            "images": records,
        }
        (stage / PROVENANCE).write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        for target in CAPTURES:
            os.replace(stage / target, destination / target)
        os.replace(stage / PROVENANCE, destination / PROVENANCE)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--ci-run", type=int, required=True)
    args = parser.parse_args()
    receipt = publish(args.source, args.destination,
                      commit=args.source_commit, run_id=args.ci_run)
    print("Published native XDG file gallery:", receipt["image_changes"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
