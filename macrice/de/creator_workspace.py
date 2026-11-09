"""On-demand Rice Creator workspace built on the existing Runtime contracts.

Every edit creates a new private version. No operation in this module selects,
applies or executes a rice; rendered previews use the separately supervised
headless labwc backend only when explicitly requested by the GUI.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import assets, creator_assets, drafts, pack, recipes, review
from .creator_contract import EDITABLE_PATHS, EDIT_VERSION, MAX_OPERATIONS

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "wayland"
TEMPLATES = {
    "heritage": ("Heritage Modern", EXAMPLES / "heritage-modern-v10.json"),
    "orbit": ("Orbit Studio", EXAMPLES / "orbit-studio-v10.json"),
    "classic": ("Classic shell", None),
    "chrome": ("Chrome shell", None),
}
MAX_LISTED_DRAFTS = 64


class WorkspaceError(ValueError):
    """Recoverable Creator authoring failure; original files remain intact."""


@dataclass(frozen=True)
class DraftInfo:
    path: Path
    name: str
    recipe_id: str
    semantic_sha256: str
    modified_ns: int


def _private_directory(*, create: bool = True) -> Path:
    """Resolve a small user-private workspace, rejecting symlinked parents."""
    configured = os.environ.get("XDG_STATE_HOME")
    root = Path(configured) if configured else Path.home() / ".local" / "state"
    if not root.is_absolute():
        raise WorkspaceError("XDG_STATE_HOME must be an absolute directory")
    directory = root / "ricebowl" / "creator" / "drafts"
    for path in (root, root / "ricebowl", root / "ricebowl" / "creator", directory):
        if create and not path.exists() and not path.is_symlink():
            path.mkdir(mode=0o700)
        try:
            mode = path.lstat()
        except FileNotFoundError as exc:
            raise WorkspaceError("Creator workspace is not available") from exc
        if (not stat.S_ISDIR(mode.st_mode) or mode.st_uid != os.geteuid()
                or mode.st_mode & 0o022 or (path == directory and mode.st_mode & 0o077)):
            raise WorkspaceError("Creator workspace has unsafe ownership or permissions")
    return directory


def _new_file(directory: Path) -> Path:
    return directory / f"draft-{secrets.token_hex(12)}.json"


def open_draft(path: Path) -> DraftInfo:
    snapshot = review.review(str(path))
    metadata = path.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077):
        raise WorkspaceError("Creator draft must be a private regular file")
    return DraftInfo(path, snapshot["recipe"]["name"], snapshot["summary"]["id"],
                     snapshot["summary"]["semantic_sha256"], metadata.st_mtime_ns)


def list_drafts() -> list[DraftInfo]:
    folder = _private_directory()
    candidates = sorted(folder.glob("draft-*.json"), key=lambda p: p.stat().st_mtime_ns
                        if not p.is_symlink() else 0, reverse=True)
    found: list[DraftInfo] = []
    for path in candidates[:MAX_LISTED_DRAFTS]:
        try:
            found.append(open_draft(path))
        except (recipes.RecipeError, WorkspaceError, OSError):
            continue  # A damaged/stale draft must not prevent opening the editor.
    return found


def create_draft(template: str, *, name: str | None = None) -> DraftInfo:
    if template not in TEMPLATES:
        raise WorkspaceError("Unknown Creator template")
    label, path = TEMPLATES[template]
    recipe_id = f"creator-{secrets.token_hex(6)}"
    title = name if name is not None else f"{label} draft"
    folder = _private_directory()
    target = _new_file(folder)
    if path is None:
        recipes.create_from_template(source=template, destination=target,
                                     recipe_id=recipe_id, name=title, schema_version=11)
    else:
        raw = recipes._read_import_source(path)
        data = json.loads(raw)
        data["id"], data["name"] = recipe_id, title
        data["schema_version"] = 11
        from .style_assets import ICON_ACTIONS
        data["artwork"] = {"font": "builtin",
                           "icons": {action: "builtin" for action in ICON_ACTIONS}}
        payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        recipes.parse(payload)
        recipes._write_private_new(target, payload)
    return open_draft(target)


def save_revision(source: Path, changes: dict[str, Any], *, expected_sha256: str) -> tuple[DraftInfo, list[dict[str, Any]]]:
    """Compare-and-swap a set of allowlisted changes into a new private file."""
    folder = _private_directory()
    if source.parent != folder or source.name.startswith("."):
        raise WorkspaceError("Open a draft from the private Creator workspace")
    original = open_draft(source)
    if original.semantic_sha256 != expected_sha256:
        raise WorkspaceError("Draft changed on disk. Reload before saving changes")
    if (not isinstance(changes, dict) or not 1 <= len(changes) <= MAX_OPERATIONS
            or any(key not in EDITABLE_PATHS for key in changes)):
        raise WorkspaceError("Choose 1–16 supported changes for one revision")
    patch = {"edit_version": EDIT_VERSION, "operations": [
        {"op": "set", "path": key, "value": value} for key, value in sorted(changes.items())]}
    payload = (json.dumps(patch, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(payload) > drafts.MAX_EDIT_BYTES:
        raise WorkspaceError("Edits exceed the safe 16 KiB draft limit")
    descriptor, patch_name = tempfile.mkstemp(prefix=".creator-edit-", suffix=".json", dir=folder)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
        destination = _new_file(folder)
        result = drafts.create_edit(recipe_token=str(source), edit_source=Path(patch_name),
                                    destination=destination)
        return open_draft(destination), result["changes"]
    finally:
        os.unlink(patch_name)


def upgrade_to_artwork(info: DraftInfo) -> DraftInfo:
    """Create a new immutable v11 draft from a saved v10 draft; never overwrite."""
    checked = open_draft(info.path)
    if checked.semantic_sha256 != info.semantic_sha256:
        raise WorkspaceError("Draft changed on disk. Reopen before upgrading")
    original = review.review(str(info.path))["recipe"]
    if original["schema_version"] != 10:
        raise WorkspaceError("Only saved v10 drafts can be upgraded")
    from .style_assets import ICON_ACTIONS
    original["schema_version"] = 11
    original["artwork"] = {"font": "builtin",
                           "icons": {action: "builtin" for action in ICON_ACTIONS}}
    payload = (json.dumps(original, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    recipes.parse(payload)
    target = _new_file(_private_directory())
    recipes._write_private_new(target, payload)
    return open_draft(target)


def export_draft(info: DraftInfo, destination: Path) -> dict[str, Any]:
    if open_draft(info.path).semantic_sha256 != info.semantic_sha256:
        raise WorkspaceError("Draft changed on disk. Reload before exporting")
    recipe = recipes.load(str(info.path))
    declared = (creator_assets.entry(recipe.wallpaper).provenance
                if assets.ASSET_ID.fullmatch(recipe.wallpaper or "") else None)
    return pack.export_pack(str(info.path), destination, wallpaper_provenance=declared)
