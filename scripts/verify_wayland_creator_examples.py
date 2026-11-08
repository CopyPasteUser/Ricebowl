#!/usr/bin/env python3
"""Render four public Creator demos through real isolated labwc/RicePlate.

Run from a normal Linux user, after building riceplate-native and installing
labwc, wlr-randr, swaybg, grim and dbus-run-session. Never touches a login shell.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image

from macrice.de import recipes, review
from scripts.compare_wayland_captures import compare


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples/wayland"
SIZES = ((1024, 768, 1.0), (1366, 768, 1.0), (1920, 1080, 1.0),
         (1366, 768, 1.25))
SCHEMAS = {"heritage-workstation": 5, "orbit-atelier": 5,
           "heritage-modern-v10": 10, "orbit-studio-v10": 10}
NAMES = tuple(SCHEMAS)


def build_gallery(destination: Path) -> dict[str, object]:
    """Write only new artifacts; callers own and create a private output dir."""
    if not destination.is_absolute() or not destination.is_dir() or any(destination.iterdir()):
        raise ValueError("Gallery destination must be an empty absolute directory")
    if os.geteuid() == 0:
        raise ValueError("Do not launch a headless compositor as root")
    if not shutil.which("dbus-run-session"):
        raise ValueError("dbus-run-session is unavailable")
    source_commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True, timeout=5).strip()
    manifest: dict[str, object] = {
        "manifest_version": 1,
        "source_commit": source_commit,
        "backend": "isolated-headless-labwc-native-riceplate",
        "capture_is_interactive": False,
        "captures": [],
    }
    hashes_by_size: dict[tuple[int, int, float], set[str]] = {}
    with tempfile.TemporaryDirectory(prefix="ricebowl-gallery-private-") as temp:
        temporary = Path(temp)
        for name in NAMES:
            source = EXAMPLES / f"{name}.json"
            payload = source.read_bytes()
            parsed = recipes.parse(payload)
            if parsed.recipe_id != name or parsed.schema_version != SCHEMAS[name]:
                raise ValueError("Example recipe ID or schema differs from contract")
            private_source = temporary / f"{name}.json"
            private_source.write_bytes(payload)
            private_source.chmod(0o600)
            semantic_hash = review._semantic_hash(review._manifest(parsed))
            for width, height, scale in SIZES:
                suffix = f"{width}x{height}-scale-{str(scale).replace('.', '-')}"
                screenshot = destination / f"{name}-{suffix}.png"
                command = [
                    "dbus-run-session", "--", "/usr/bin/python3",
                    str(ROOT / "launcher.py"), "de", "render",
                    "--recipe", str(private_source), "--output", str(screenshot),
                    "--width", str(width), "--height", str(height),
                    "--scale", str(scale), "--json",
                ]
                result = subprocess.run(command, cwd=ROOT, capture_output=True,
                                        text=True, check=True, timeout=70)
                receipt = json.loads(result.stdout)
                if (not receipt.get("ok") or receipt.get("creator_contract_version") != 1
                        or receipt["render"]["recipe"]["semantic_sha256"] != semantic_hash
                        or receipt["render"]["source"] != manifest["backend"]):
                    raise ValueError("Creator render receipt does not match its recipe")
                with Image.open(screenshot) as image:
                    if image.format != "PNG" or image.size != (width, height):
                        raise ValueError("Native screenshot has wrong format or dimensions")
                    image.verify()
                contents = screenshot.read_bytes()
                digest = hashlib.sha256(contents).hexdigest()
                if receipt["render"]["output"]["sha256"] != digest:
                    raise ValueError("Native screenshot hash disagrees with render receipt")
                diagnostics = compare(screenshot, screenshot, recipe_token=str(private_source))
                if diagnostics["layout_issues"]:
                    raise ValueError("Native capture has invalid visible geometry")
                hashes_by_size.setdefault((width, height, scale), set()).add(digest)
                manifest["captures"].append({
                    "file": screenshot.name,
                    "recipe": name,
                    "schema_version": parsed.schema_version,
                    "recipe_source_sha256": hashlib.sha256(payload).hexdigest(),
                    "semantic_sha256": semantic_hash,
                    "width": width, "height": height, "scale": scale,
                    "capture_sha256": digest,
                    "regions": [{key: item[key] for key in
                                 ("id", "expected_rect", "visible_fraction")}
                                for item in diagnostics["regions"]],
                    "layout_issues": [],
                })
    if len(manifest["captures"]) != len(NAMES) * len(SIZES) or any(
            len(digests) != len(NAMES) for digests in hashes_by_size.values()):
        raise ValueError("Distinct rice previews were not captured at every size")
    destination.joinpath("manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="An existing, empty, absolute output directory")
    arguments = parser.parse_args()
    result = build_gallery(arguments.output_dir)
    print(json.dumps({"ok": True, "capture_count": len(result["captures"]),
                      "manifest": str(arguments.output_dir / "manifest.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
