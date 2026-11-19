"""Byte-pinned, non-activating Creator GUI export review.

Reviewing a RicePack verifies *declared* provenance and embedded byte integrity.
It never confers redistribution rights or changes the active desktop.
"""
from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import creator_workspace as workspace, pack


class ReleaseError(ValueError):
    """The reviewed Creator export is stale or has inconsistent bytes."""


@dataclass(frozen=True)
class ReleaseReview:
    draft: workspace.DraftInfo
    payload: bytes
    package_sha256: str
    manifest: dict[str, Any]
    attribution_review: dict[str, Any]
    entries: tuple[tuple[str, str, str, dict[str, str]], ...]


def _entries(manifest: dict[str, Any]) -> tuple[tuple[str, str, str, dict[str, str]], ...]:
    """Read verified receipts, not untrusted file names or free-form archives."""
    entries = [("rice", manifest["recipe"]["id"],
                manifest["recipe"]["semantic_sha256"], manifest["provenance"])]
    assets = manifest.get("asset_manifest")
    if assets:
        wallpaper = assets["wallpaper"]
        entries.append(("wallpaper", wallpaper["id"], wallpaper["sha256"],
                        wallpaper["provenance"]))
        visual = assets.get("visual", {})
        font = visual.get("font")
        if font:
            entries.append(("font", font["id"], font["sha256"], font["provenance"]))
        for action, icon in sorted(visual.get("icons", {}).items()):
            entries.append((f"icon:{action}", icon["id"], icon["sha256"],
                            icon["provenance"]))
    return tuple(entries)


def prepare_export(draft: workspace.DraftInfo) -> ReleaseReview:
    """Inspect the exact self-contained package that the GUI may later publish.

    A private temporary directory is used so cancel never creates the selected
    destination; the reviewed package bytes are retained for a no-TOCTOU export.
    """
    checked = workspace.open_draft(draft.path)
    if (checked.semantic_sha256 != draft.semantic_sha256
            or checked.recipe_id != draft.recipe_id):
        raise ReleaseError("Saved Creator version changed; reopen and review it")
    with tempfile.TemporaryDirectory(prefix="ricebowl-export-review-") as folder:
        archive = Path(folder) / "review.ricepack"
        result = workspace.export_draft(checked, archive)
        inspected = pack.inspect_pack(archive)
        payload = pack._read_owned_file(
            archive, suffix=".ricepack", limit=pack.MAX_PACK_BYTES, owner_private=True)
    digest = hashlib.sha256(payload).hexdigest()
    if (not inspected["valid"] or inspected["manifest"] != result["manifest"]
            or digest != result["package_sha256"]
            or inspected["manifest"]["recipe"]["semantic_sha256"] != draft.semantic_sha256):
        raise ReleaseError("Reviewed package or manifest does not match the saved version")
    return ReleaseReview(checked, payload, digest, inspected["manifest"],
                         inspected["compatibility"]["attribution_review"],
                         _entries(inspected["manifest"]))


def review_text(plan: ReleaseReview) -> str:
    """Plain text for an actual accessible GTK review dialog."""
    lines = [
        f"Rice: {plan.draft.recipe_id}",
        f"Recipe SHA-256: {plan.draft.semantic_sha256}",
        f"RicePack SHA-256: {plan.package_sha256}",
        f"Format: RicePack v{plan.manifest['format_version']}",
        "",
        "EMBEDDED ASSET / ATTRIBUTION RECEIPTS",
    ]
    for kind, identifier, digest, declaration in plan.entries:
        lines.extend((
            f"{kind}: {identifier}",
            f"  SHA-256: {digest}",
            f"  Author: {declaration['author'] or '(not declared)'}",
            f"  License: {declaration['license']}",
            f"  Origin: {declaration['origin']}",
            f"  Source: {declaration['source_reference'] or '(not declared)'}",
        ))
    missing = plan.attribution_review["missing_fields"]
    lines.extend(("", "Attribution declarations: " +
                  ("INCOMPLETE — " + ", ".join(missing) if missing else "complete"),
                  "Checksums establish byte integrity, NOT ownership or redistribution rights.",
                  "Independent legal/asset review remains required before sharing."))
    return "\n".join(lines)


def publish_export(plan: ReleaseReview, destination: Path) -> dict[str, Any]:
    """Publish only the reviewed bytes, atomically, without overwrite/apply.

    Revalidate the original saved version, immutable archive and receipt.
    Assets changed after review cannot silently replace its exported bytes.
    """
    checked = workspace.open_draft(plan.draft.path)
    if (checked.semantic_sha256 != plan.draft.semantic_sha256
            or checked.recipe_id != plan.draft.recipe_id):
        raise ReleaseError("Saved Creator version changed since export review")
    if hashlib.sha256(plan.payload).hexdigest() != plan.package_sha256:
        raise ReleaseError("Reviewed RicePack bytes changed")
    manifest, _, _, _, _ = pack._validate_archive(plan.payload)
    if (manifest != plan.manifest
            or manifest["recipe"]["semantic_sha256"] != plan.draft.semantic_sha256):
        raise ReleaseError("Reviewed RicePack manifest changed")
    pack._new_archive(destination, plan.payload)
    return {"package_sha256": plan.package_sha256,
            "recipe_id": plan.draft.recipe_id,
            "attribution_declarations_complete":
                plan.attribution_review["declarations_complete"],
            "rights_independently_verified": False,
            "applied": False}
