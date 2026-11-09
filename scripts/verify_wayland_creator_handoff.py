#!/usr/bin/env python3
"""Exercise real Creator-generated recipes through native headless Wayland.

Creates two private drafts, edits/forks one, installs both explicitly, then
renders the *installed IDs* in isolated labwc/RicePlate sessions. It never
selects a login rice, switches the user's desktop or runs generated scripts.
The captures prove rendering, not input/focus or real-device compatibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from PIL import Image

from macrice.de import creator_activation, creator_workspace, recipes, render


ROOT = Path(__file__).resolve().parents[1]
GEOMETRIES = ((1024, 768, 1.0), (1366, 768, 1.25))


def capture_installed(destination: Path) -> dict:
    if (not destination.is_absolute() or not destination.is_dir()
            or any(destination.iterdir())):
        raise ValueError("Provide an existing, empty, absolute output directory")
    if os.geteuid() == 0:
        raise ValueError("Run native Wayland QA as an unprivileged user")
    missing = [tool for tool in (*render.REQUIRED, "dbus-run-session")
               if shutil.which(tool) is None]
    if missing:
        raise ValueError("Missing native Wayland tools: " + ", ".join(missing))

    sha = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True, timeout=5).strip()
    result = {"manifest_version": 1, "source_commit": sha,
              "capture_is_interactive": False,
              "backend": "isolated-headless-labwc-native-riceplate",
              "captures": []}
    with tempfile.TemporaryDirectory(prefix="ricebowl-creator-native-qa-") as directory:
        root = Path(directory)
        state, config = root / "state", root / "config"
        state.mkdir(mode=0o700)
        config.mkdir(mode=0o700)
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(state),
                                          "XDG_CONFIG_HOME": str(config)}):
            heritage = creator_workspace.create_draft("heritage")
            revised, _ = creator_workspace.save_revision(
                heritage.path, {"/panel/height": 48},
                expected_sha256=heritage.semantic_sha256)
            updated_heritage = creator_workspace.fork_version(revised)
            orbit = creator_workspace.create_draft("orbit")
            drafts = (updated_heritage, orbit)
            if recipes.current_selection() != ("classic", None):
                raise ValueError("Creator staging unexpectedly changed login state")
            for draft in drafts:
                plan = creator_activation.inspect_install(draft)
                if not creator_activation.install(plan):
                    raise ValueError("Fresh Creator draft was already installed")
                if recipes.current_selection() != ("classic", None):
                    raise ValueError("Offline installation changed the login selection")
                if recipes.load(draft.recipe_id).recipe_id != draft.recipe_id:
                    raise ValueError("Installed recipe differs from private draft")
                for width, height, scale in GEOMETRIES:
                    name = (f"{draft.recipe_id}-{width}x{height}-"
                            f"scale-{str(scale).replace('.', '-')}.png")
                    output = destination / name
                    receipt = render.render(draft.recipe_id, output, width=width,
                                            height=height, scale=scale)
                    if (receipt["recipe"]["semantic_sha256"] != draft.semantic_sha256
                            or receipt["recipe"]["id"] != draft.recipe_id
                            or receipt["source"] != result["backend"]
                            or receipt["mutates_active_desktop"] is not False
                            or receipt["interactive_session"] is not False):
                        raise ValueError("Native render receipt does not match Creator draft")
                    payload = output.read_bytes()
                    if (payload[:8] != bytes.fromhex("89504e470d0a1a0a")
                            or struct.unpack(">II", payload[16:24]) != (width, height)):
                        raise ValueError("Native capture is not the expected PNG geometry")
                    with Image.open(output) as image:
                        if image.format != "PNG" or image.size != (width, height):
                            raise ValueError("Native screenshot dimensions mismatch")
                        image.verify()
                    digest = hashlib.sha256(payload).hexdigest()
                    if receipt["output"]["sha256"] != digest:
                        raise ValueError("Native screenshot receipt digest mismatch")
                    result["captures"].append({
                        "file": name, "recipe": draft.recipe_id,
                        "schema_version": recipes.load(draft.recipe_id).schema_version,
                        "semantic_sha256": draft.semantic_sha256,
                        "width": width, "height": height, "scale": scale,
                        "capture_sha256": digest,
                    })
            if recipes.current_selection() != ("classic", None):
                raise ValueError("Native preview changed the login selection")
    if len(result["captures"]) != 2 * len(GEOMETRIES):
        raise ValueError("Expected four independent native Creator captures")
    if len({item["capture_sha256"] for item in result["captures"]}) != len(result["captures"]):
        raise ValueError("Distinct Creator captures unexpectedly have identical pixels")
    (destination / "manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    options = parser.parse_args()
    manifest = capture_installed(options.output_dir)
    print(json.dumps({"ok": True, "captures": len(manifest["captures"]),
                      "manifest": str(options.output_dir / "manifest.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
