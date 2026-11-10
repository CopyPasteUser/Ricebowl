"""Reproducible, content-addressed source copies for offline Creator authoring.

The source is parsed once and canonicalized through the runtime manifest.
Snapshots are private, no-overwrite 0400 files named by their exact byte hash.
The normal recipes.load() path verifies that hash on *every* subsequent read.
An owner can deliberately chmod/replace their files; this is not a privileged
kernel immutable flag or a substitute for an off-machine backup.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from . import creator_workspace, recipes, review


class SnapshotError(ValueError):
    """Cannot safely create or reuse a verified Creator source snapshot."""


def _private_directory() -> Path:
    try:
        directory = creator_workspace._private_directory().parent / "snapshots"
        if not directory.exists() and not directory.is_symlink():
            directory.mkdir(mode=0o700)
        meta = directory.lstat()
        if (not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.geteuid()
                or meta.st_mode & 0o077):
            raise SnapshotError("Creator snapshots require an owner-private directory")
        return directory
    except (creator_workspace.WorkspaceError, OSError) as exc:
        raise SnapshotError("Private Creator snapshot storage is unavailable") from exc


def create(recipe_token: str) -> dict[str, object]:
    """Copy a validated semantic recipe to a deterministic never-overwritten file."""
    try:
        original = recipes.load(recipe_token)
        manifest = review._manifest(original)
        semantic_sha = review._semantic_hash(manifest)
        payload = (json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")) + "\n").encode("utf-8")
        if len(payload) > recipes.MAX_RECIPE_BYTES:
            raise SnapshotError("Canonical recipe exceeds the private recipe size limit")
        reparsed = recipes.parse(payload)
        if review._semantic_hash(review._manifest(reparsed)) != semantic_sha:
            raise SnapshotError("Canonical snapshot does not preserve source semantics")
        content_sha = hashlib.sha256(payload).hexdigest()
        destination = _private_directory() / f"snapshot-{content_sha}.json"
        created = True
        try:
            recipes._write_private_new(destination, payload, mode=0o400)
        except FileExistsError:
            created = False
        # Reject tampered/unsafe pre-existing files; never chmod or replace them.
        verified = recipes.load(str(destination))
        if destination.lstat().st_mode & 0o777 != 0o400:
            raise SnapshotError("Creator snapshot must retain its 0400 read-only mode")
        if review._semantic_hash(review._manifest(verified)) != semantic_sha:
            raise SnapshotError("Saved snapshot differs from its reviewed source")
        return {"ok": True, "applied": False, "created": created,
                "recipe_id": original.recipe_id, "schema_version": original.schema_version,
                "source_semantic_sha256": semantic_sha, "content_sha256": content_sha,
                "path": str(destination), "mode": "0400"}
    except recipes.RecipeError as exc:
        raise SnapshotError("Recipe or snapshot failed its full integrity validation") from exc
    except OSError as exc:
        raise SnapshotError("Could not publish a private Creator snapshot") from exc
