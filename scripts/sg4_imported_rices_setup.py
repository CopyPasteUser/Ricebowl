#!/usr/bin/env python3
"""Disposable Creator -> RicePack -> import path for the two SG4 rices.

The two "imported rices" of SG4 are the Heritage Composer and Orbit Composer
Creator templates (schema v10 examples, saved as private v11 drafts). This
helper drives the REAL Creator backend (`creator_workspace`, `pack`) and never
touches anything outside the XDG/HOME directories it is given:

  author  ARCHIVE_DIR   (run with the AUTHOR profile in XDG_CONFIG_HOME/STATE)
      create the two drafts, save one reviewed revision each, export a
      verified RicePack per draft. Prints JSON {"packs": [...]}.
  import  ARCHIVE_DIR   (run with a DIFFERENT, fresh XDG_CONFIG_HOME)
      read-only inspect + preflight, then the locked import of each pack.
      Nothing is applied or staged. Prints JSON {"rices": [{id, name,
      semantic_sha256, position, menu_presentation, recipe_path}, ...]}.

The saved selection must stay `classic` throughout; anything else is a
failure, so a smoke built on this can never silently change a login.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from macrice.de import creator_workspace, pack, recipes  # noqa: E402

TEMPLATES = ("heritage-composer", "orbit-composer")


def _require_classic() -> None:
    if recipes.current_selection() != ("classic", None):
        raise SystemExit("FAIL: Creator step changed the login selection")


def author(archives: Path) -> dict:
    _require_classic()
    packs = []
    for template in TEMPLATES:
        draft = creator_workspace.create_draft(template)
        revised, _ = creator_workspace.save_revision(
            draft.path, {"/name": f"SG4 {template}"},
            expected_sha256=draft.semantic_sha256)
        archive = archives / f"{template}.ricepack"
        exported = creator_workspace.export_draft(revised, archive)
        inspected = pack.inspect_pack(archive)
        if inspected["manifest"] != exported["manifest"] or inspected["imported"]:
            raise SystemExit("FAIL: inspection changed the pack semantics")
        packs.append({"template": template, "recipe_id": revised.recipe_id,
                      "semantic_sha256": revised.semantic_sha256,
                      "package_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                      "archive": str(archive)})
    _require_classic()
    return {"packs": packs}


def import_all(archives: Path) -> dict:
    _require_classic()
    config_root = Path(os.environ["XDG_CONFIG_HOME"])
    rices = []
    for template in TEMPLATES:
        archive = archives / f"{template}.ricepack"
        inspection = pack.inspect_pack(archive)
        before = (config_root / "ricebowl").exists()
        ready = pack.preflight_import(archive, expected_manifest=inspection["manifest"])
        if (not ready["ready"] or ready["imported"] or ready["applied"]
                or (not before and (config_root / "ricebowl").exists())):
            raise SystemExit("FAIL: preflight wrote to the import profile")
        imported = pack.import_pack(archive, expected_manifest=inspection["manifest"])
        if not imported["imported"] or imported["applied"]:
            raise SystemExit("FAIL: import applied or did not install the rice")
        recipe = recipes.load(imported["recipe_id"])
        rices.append({
            "template": template,
            "id": imported["recipe_id"],
            "name": recipe.name,
            "semantic_sha256": imported["semantic_sha256"],
            "schema_version": recipe.schema_version,
            "position": recipe.position,
            "menu_presentation": recipe.menu_presentation if recipe.menu else None,
            "recipe_path": recipes.native_token(imported["recipe_id"]),
        })
    _require_classic()
    return {"rices": rices}


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("author", "import"):
        print(__doc__, file=sys.stderr)
        return 2
    if os.geteuid() == 0:
        print("FAIL: run as an unprivileged user", file=sys.stderr)
        return 2
    folder = Path(argv[2])
    result = author(folder) if argv[1] == "author" else import_all(folder)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
