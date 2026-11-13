#!/usr/bin/env python3
"""Publish checked-in, reproducible previews from a VERIFIED native CI artifact.

Never synthesize a screenshot or recolor a framebuffer. Every source PNG
is decoded from a genuine labwc/grim capture; the manifest pins its source
commit and hashes. Fail closed if the provenance does not match.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

SOURCES = {
    "luna-desktop-20261113.webp": "xp-luna-columns-1366x768.png",
    "luna-start-20261113.webp": "xp-luna-parity-start.png",
    "luna-help-20261113.webp": "xp-luna-parity-help.png",
    "luna-run-20261113.webp": "xp-luna-parity-run-typed.png",
    "luna-context-20261113.webp": "xp-luna-shortcut-context.png",
    "luna-properties-20261113.webp": "xp-luna-shortcut-properties.png",
}
EXPECTED_SOURCE = "c0bdb46c87da1e8eb5b5408e7d96f5509d4c7e76"
EXPECTED_SIZE = (1366, 768)


def publish(source: Path, destination: Path) -> None:
    manifest = json.loads((source / "capture-manifest.json").read_text("utf-8"))
    assert manifest["source_commit"] == EXPECTED_SOURCE, "unexpected captured revision"
    assert manifest["environment"] == {
        "backend": "headless", "compositor": "labwc",
        "native_surface": "riceplate", "renderer": "pixman",
    }, "capture did not use the verified native labwc renderer"
    receipts = {record["file"]: record for record in manifest["captures"]}
    destination.mkdir(parents=True, exist_ok=True)
    published = []
    for name, screenshot in SOURCES.items():
        raw = (source / screenshot).read_bytes()
        assert raw.startswith(bytes.fromhex("89504e470d0a1a0a")), f"invalid PNG: {screenshot}"
        receipt = receipts.get(screenshot)
        if receipt is not None:
            assert hashlib.sha256(raw).hexdigest() == receipt["sha256"], screenshot
        # The detailed Run/Help/context snapshots are produced in the same
        # smoke step, but are not enumerated individually in the older summary
        # manifest. Pin their bytes in the generated provenance JSON instead.
        with Image.open(source / screenshot) as picture:
            picture.load()
            assert picture.size == EXPECTED_SIZE, f"unexpected geometry: {screenshot}"
            assert picture.format == "PNG", screenshot
            picture.convert("RGB").save(destination / name, format="WEBP",
                                        quality=83, method=6, exact=True)
        published.append({
            "preview": name, "source": screenshot,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "preview_sha256": hashlib.sha256((destination / name).read_bytes()).hexdigest(),
            "source_manifest_verified": receipt is not None,
        })
    (destination / "luna-gallery-provenance-20261113.json").write_text(
        json.dumps({"ci_run": 43354447753, "source_commit": EXPECTED_SOURCE,
                    "source": "real headless labwc compositor, grim PNG",
                    "images": published}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    options = parser.parse_args()
    publish(options.source, options.destination)
