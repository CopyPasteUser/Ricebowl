#!/usr/bin/env python3
"""Exercise portable Creator recipes through native headless Wayland.

Creates and edits two genuinely different private drafts, exports verified
offline RicePacks, imports them into a separate private recipe collection,
renders the *imported IDs* and tests explicit next-login stage/rollback.
Only disposable XDG directories are touched; the captures prove rendering,
not input/focus or real-device compatibility.
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

from macrice.de import creator_workspace, pack, recipes, render, staging, style_assets


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
              "captures": [], "package_imports": []}
    with tempfile.TemporaryDirectory(prefix="ricebowl-creator-native-qa-") as directory:
        root = Path(directory)
        state, config, imported_config = (root / "state", root / "author-config",
                                          root / "import-config")
        state.mkdir(mode=0o700)
        config.mkdir(mode=0o700)
        imported_config.mkdir(mode=0o700)
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(state),
                                          "XDG_CONFIG_HOME": str(config)}):
            # Original, generated 48px PNG artwork must survive a *different*
            # XDG config root; merely reusing the author's asset store cannot
            # exercise portable RicePack v4 payloads.
            icons = []
            for index, color in enumerate(((12, 92, 200, 255), (30, 150, 80, 255))):
                source = root / f"creator-qa-icon-{index}.png"
                Image.new("RGBA", (48, 48), color).save(source)
                item = style_assets.import_asset(
                    source, kind="icon", label=f"Creator QA icon {index + 1}",
                    provenance={"author": "RiceBowl test suite", "license": "CC0-1.0",
                                "origin": "original", "source_reference": ""})
                icons.append(item.identifier)
            heritage = creator_workspace.create_draft("heritage")
            revised, _ = creator_workspace.save_revision(
                heritage.path, {"/panel/height": 48,
                                "/artwork/icons/applications": icons[0]},
                expected_sha256=heritage.semantic_sha256)
            updated_heritage = creator_workspace.fork_version(revised)
            orbit = creator_workspace.create_draft("orbit")
            revised_orbit, _ = creator_workspace.save_revision(
                orbit.path, {"/name": "Orbit Studio offline QA",
                             "/artwork/icons/applications": icons[1]},
                expected_sha256=orbit.semantic_sha256)
            drafts = (updated_heritage, revised_orbit)
            if recipes.current_selection() != ("classic", None):
                raise ValueError("Creator staging unexpectedly changed login state")
            archives = []
            for draft in drafts:
                archive = root / f"{draft.recipe_id}.ricepack"
                exported = creator_workspace.export_draft(draft, archive)
                inspected = pack.inspect_pack(archive)
                if (inspected["manifest"] != exported["manifest"]
                        or inspected["imported"] or inspected["applied"]):
                    raise ValueError("Offline RicePack inspection changed package semantics")
                archives.append(archive)
            os.environ["XDG_CONFIG_HOME"] = str(imported_config)
            if recipes.current_selection() != ("classic", None):
                raise ValueError("Fresh importer unexpectedly inherited author configuration")
            for draft, archive in zip(drafts, archives):
                imported = pack.import_pack(archive)
                if (not imported["imported"] or imported["applied"]
                        or imported["semantic_sha256"] != draft.semantic_sha256
                        or imported["recipe_id"] != draft.recipe_id):
                    raise ValueError("Offline RicePack did not install the reviewed Creator rice")
                result["package_imports"].append({
                    "recipe": draft.recipe_id,
                    "pack_version": imported["pack_version"],
                    "semantic_sha256": draft.semantic_sha256,
                    "package_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                })
                if recipes.current_selection() != ("classic", None):
                    raise ValueError("Offline RicePack import changed the login selection")
                installed_recipe = recipes.load(draft.recipe_id)
                if installed_recipe.recipe_id != draft.recipe_id:
                    raise ValueError("Imported recipe differs from private draft")
                visual_id = installed_recipe.artwork.icons[0]
                if visual_id not in icons:
                    raise ValueError("RicePack v4 lost the Creator icon reference")
                imported_icon = style_assets.entry(visual_id)
                source_icon = root / f"creator-qa-icon-{icons.index(visual_id)}.png"
                if (imported_icon.provenance["license"] != "CC0-1.0"
                        or style_assets.read(visual_id) != source_icon.read_bytes()):
                    raise ValueError("RicePack v4 lost portable icon bytes or attribution")
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
            # Test the explicit selection path only *after* native captures.
            # Rollback retains the one-level previous ID by design, so its
            # isolated QA state must not be confused with an untouched login.
            for draft in drafts:
                staged = staging.stage(draft.recipe_id, draft.semantic_sha256,
                                       expected_active="classic")
                if (staged["next_session"] != draft.recipe_id
                        or recipes.selected_recipe() != draft.recipe_id):
                    raise ValueError("Imported rice could not be staged for the next login")
                restored = staging.rollback(expected_active=draft.recipe_id)
                if (restored["next_session"] != "classic"
                        or recipes.selected_recipe() != "classic"):
                    raise ValueError("Staged imported rice could not be rolled back")
    if len(result["package_imports"]) != 2 or len({
            item["semantic_sha256"] for item in result["package_imports"]}) != 2:
        raise ValueError("Expected two distinct verified offline Creator imports")
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
