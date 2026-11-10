"""Offline Creator recovery from a verified parent, never in-place repair.

An interrupted version publication can leave a .history intent without its
recipe. A damaged newer draft can also remain on disk. Neither case should
make the last verified ancestor unusable or cause silent data loss.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import creator_history, creator_workspace, recipes, review


class RecoveryError(ValueError):
    """A private version has no safe, verified recovery parent."""


MAX_RECOVERY_SCAN = 128


def scan() -> dict[str, object]:
    """Read-only, bounded discovery of missing/damaged Creator publications."""
    empty = {"ok": True, "applied": False, "scanned_receipts": 0,
             "truncated": False, "unresolved": []}
    try:
        try:
            folder = creator_workspace._private_directory(create=False)
        except creator_workspace.WorkspaceError as exc:
            if str(exc) == "Creator workspace is not available":
                return empty  # Fresh installation: do not create directories while scanning.
            raise
        records: list[Path] = []
        with os.scandir(folder) as entries:
            for entry in entries:
                if (entry.name.endswith(".history") and
                        creator_history._DRAFT_NAME.fullmatch(
                            entry.name.removesuffix(".history") + ".json")):
                    records.append(folder / entry.name)
                    if len(records) > MAX_RECOVERY_SCAN:
                        break
        unresolved: list[dict[str, object]] = []
        for intent in sorted(records[:MAX_RECOVERY_SCAN]):
            draft = intent.with_suffix(".json")
            try:
                creator_workspace.open_draft(draft)
                continue
            except (creator_workspace.WorkspaceError, recipes.RecipeError, OSError):
                pass
            try:
                unresolved.append(inspect(draft))
            except RecoveryError:
                unresolved.append({"source": str(draft), "recoverable": False,
                                   "source_status": ("unverified" if draft.exists() or
                                                     draft.is_symlink() else "missing"),
                                   "error": {"code": "unverified_history"}})
        return {"ok": True, "applied": False, "scanned_receipts": min(len(records),
                MAX_RECOVERY_SCAN), "truncated": len(records) > MAX_RECOVERY_SCAN,
                "unresolved": unresolved}
    except (creator_workspace.WorkspaceError, OSError) as exc:
        raise RecoveryError("Private Creator recovery collection is unavailable") from exc


def inspect(path: Path) -> dict[str, object]:
    """Find the authenticated preceding version even if this recipe is damaged."""
    try:
        folder = creator_workspace._private_directory(create=False)
        if (not path.is_absolute() or path.parent != folder or
                creator_history._DRAFT_NAME.fullmatch(path.name) is None):
            raise RecoveryError("Recovery requires a private Creator draft path")
        receipt = creator_history.inspect_intent(path)
        if receipt is None:
            raise RecoveryError("No verified history receipt; legacy draft recovery is unavailable")
        if receipt["parent"] is None:
            raise RecoveryError("This draft has no recorded parent to recover")
        entry = receipt["parent"]
        seen = {path}
        skipped = 0
        # A failed edit may be followed by more than one damaged revision.
        # Walk *receipts* through those gaps, but select only a fully validated
        # ancestor with the exact hash advertised by its child.
        for _ in range(creator_history.MAX_HISTORY_DEPTH):
            candidate = folder / entry["filename"]
            if candidate in seen:
                raise RecoveryError("Creator recovery history contains a cycle")
            seen.add(candidate)
            try:
                parent = creator_workspace.open_draft(candidate)
                if parent.semantic_sha256 == entry["semantic_sha256"]:
                    break
            except (creator_workspace.WorkspaceError, recipes.RecipeError, OSError):
                pass
            skipped += 1
            prior_intent = creator_history.inspect_intent(candidate)
            if (prior_intent is None or
                    prior_intent["target_semantic_sha256"] != entry["semantic_sha256"] or
                    prior_intent["parent"] is None):
                raise RecoveryError("Last verified ancestor cannot be traced past a damaged version")
            entry = prior_intent["parent"]
        else:
            raise RecoveryError("Creator recovery exceeds the bounded history depth")
        try:
            child = creator_workspace.open_draft(path)
            status = ("verified" if child.semantic_sha256 == receipt["target_semantic_sha256"]
                      else "unverified")
        except (creator_workspace.WorkspaceError, recipes.RecipeError, OSError):
            status = "unverified" if path.exists() or path.is_symlink() else "missing"
        return {"ok": True, "applied": False, "recoverable": True,
                "source": str(path), "source_status": status,
                "source_expected_sha256": receipt["target_semantic_sha256"],
                "parent": str(parent.path), "parent_semantic_sha256": parent.semantic_sha256,
                "recipe_id": parent.recipe_id, "skipped_unverified_versions": skipped}
    except (creator_history.HistoryError, creator_workspace.WorkspaceError,
            recipes.RecipeError, OSError) as exc:
        raise RecoveryError("Creator recovery chain is missing, damaged or unsafe") from exc


def recover(path: Path, *, expected_parent_sha256: str) -> dict[str, object]:
    """Copy the verified ancestor as a NEW version after explicit hash review."""
    if (type(expected_parent_sha256) is not str or
            re.fullmatch(r"[0-9a-f]{64}", expected_parent_sha256) is None):
        raise RecoveryError("Recovery requires the reviewed parent SHA-256")
    details = inspect(path)
    if details["parent_semantic_sha256"] != expected_parent_sha256:
        raise RecoveryError("Recovery parent changed; inspect the history again")
    parent = Path(str(details["parent"]))
    try:
        # Build from one freshly loaded, validated recipe. Do not trust any
        # bytes from the damaged version, or copy a stale source after review.
        original = recipes.load(str(parent))
        manifest = review._manifest(original)
        if review._semantic_hash(manifest) != expected_parent_sha256:
            raise RecoveryError("Verified recovery parent changed while copying")
        payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        saved = creator_workspace._publish_version(
            creator_workspace._new_file(parent.parent), payload, "recover",
            parent=(parent.name, expected_parent_sha256))
    except (recipes.RecipeError, creator_workspace.WorkspaceError, OSError) as exc:
        raise RecoveryError("Recovery copy could not be published safely") from exc
    return {"ok": True, "applied": False, "created": True,
            "recipe_id": saved.recipe_id, "path": str(saved.path),
            "semantic_sha256": saved.semantic_sha256,
            "recovered_from": str(parent), "unmodified_source": str(path),
            "source_status": details["source_status"]}
