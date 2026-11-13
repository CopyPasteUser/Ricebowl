#!/usr/bin/env python3
"""Import genuine, verified labwc/grim captures from a Native RicePlate CI artifact.

Usage: python3 scripts/import_native_wayland_gallery.py --source dist/riceplate-preview \
           --destination screenshots/wayland --ci-run 43368674306 \
           --source-commit bdbae75b4c3fbc1c721fed4c20a231c227ef0a54

The caller must download an artifact from a successful, matching CI run.
Never synthesize/repaint a screenshot; WebP compression is the only image edit.
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

EXPECTED_ENV = {
    "backend": "headless", "compositor": "labwc",
    "native_surface": "riceplate", "renderer": "pixman",
}
# Source name, expected framebuffer dimensions. Keep the six public URLs stable.
CAPTURES = {
    "luna-desktop-20261113.webp": ("xp-luna-columns-1366x768.png", (1366, 768)),
    "luna-start-20261113.webp": ("xp-luna-parity-start.png", (1366, 768)),
    "luna-help-20261113.webp": ("xp-luna-parity-help.png", (1366, 768)),
    "luna-run-20261113.webp": ("xp-luna-parity-run-typed.png", (1366, 768)),
    "luna-context-20261113.webp": ("xp-luna-shortcut-context.png", (1366, 768)),
    "luna-properties-20261113.webp": ("xp-luna-shortcut-properties.png", (1366, 768)),
    "luna-calendar-20261113.webp": ("xp-luna-columns-calendar.png", (1366, 768)),
    "luna-all-programs-20261113.webp": ("xp-luna-pointer-programs-1024x768.png", (1024, 768)),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def import_gallery(source: Path, destination: Path, *, ci_run: int, commit: str) -> dict:
    if ci_run <= 0 or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A positive CI run ID and full 40-character commit SHA are required")
    manifest = json.loads((source / "capture-manifest.json").read_text("utf-8"))
    if manifest.get("source_commit") != commit or manifest.get("environment") != EXPECTED_ENV:
        raise ValueError("Artifact does not match the specified revision or native capture environment")
    receipts = {record["file"]: record for record in manifest.get("captures", [])}
    if not receipts:
        raise ValueError("Native capture manifest has no source receipts")

    # Stage and validate *all* frames before any public screenshot is replaced.
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".luna-gallery-", dir=destination) as temporary:
        stage = Path(temporary)
        records = []
        for target, (name, expected_size) in CAPTURES.items():
            path = source / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Missing or unsafe source PNG: {name}")
            raw = path.read_bytes()
            if not (12_000 < len(raw) < 12_000_000 and raw.startswith(b"\x89PNG\r\n\x1a\n")):
                raise ValueError(f"Invalid PNG: {name}")
            receipt = receipts.get(name)
            if receipt is not None and receipt.get("sha256") != sha256(raw):
                raise ValueError(f"Native manifest hash mismatch: {name}")
            with Image.open(path) as screenshot:
                screenshot.load()
                if screenshot.format != "PNG" or screenshot.size != expected_size:
                    raise ValueError(f"Unexpected screenshot type or geometry: {name}")
                rgb = screenshot.convert("RGB")
                if max(ImageStat.Stat(rgb.resize((32, 18))).stddev) < 12:
                    raise ValueError(f"Screenshot appears blank: {name}")
                rgb.save(stage / target, format="WEBP", quality=83, method=6)
            with Image.open(stage / target) as preview:
                if preview.format != "WEBP" or preview.size != expected_size:
                    raise ValueError(f"WebP verification failed: {target}")
            records.append({
                "preview": target,
                "source": name,
                "size": list(expected_size),
                "source_sha256": sha256(raw),
                "preview_sha256": sha256((stage / target).read_bytes()),
                "source_manifest_verified": receipt is not None,
            })
        provenance = {
            "ci_run": ci_run,
            "source_commit": commit,
            "environment": EXPECTED_ENV,
            "source": "Native RicePlate CI: genuine headless labwc/grim compositor PNG",
            "images": records,
        }
        (stage / "luna-gallery-provenance-20261113.json").write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        for item in records:
            os.replace(stage / item["preview"], destination / item["preview"])
        os.replace(stage / "luna-gallery-provenance-20261113.json",
                   destination / "luna-gallery-provenance-20261113.json")
    return provenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", default=Path("screenshots/wayland"), type=Path)
    parser.add_argument("--ci-run", required=True, type=int)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    result = import_gallery(args.source, args.destination, ci_run=args.ci_run,
                            commit=args.source_commit)
    print(f"Published {len(result['images'])} native screenshots from {result['source_commit']}")
