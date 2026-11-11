"""On-demand Rice Creator workspace built on the existing Runtime contracts.

Every edit creates a new private version. No operation in this module selects,
applies or executes a rice; rendered previews use the separately supervised
headless labwc backend only when explicitly requested by the GUI.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import assets, creator_assets, creator_history, drafts, pack, recipes, review
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
    info = DraftInfo(path, snapshot["recipe"]["name"], snapshot["summary"]["id"],
                     snapshot["summary"]["semantic_sha256"], metadata.st_mtime_ns)
    if path.parent == _private_directory() and path.name.startswith("draft-"):
        try:
            creator_history.read(path, info.semantic_sha256)
        except creator_history.HistoryError as exc:
            raise WorkspaceError(str(exc)) from exc
    return info


def _publish_version(target: Path, payload: bytes, kind: str, *,
                     parent: tuple[str, str] | None = None) -> DraftInfo:
    """Publish intent first, then recipe; a crash never exposes receiptless new drafts.

    An interrupted publication may leave an orphan .history intent, which is
    deliberately never treated as a visible draft. No existing file is erased.
    """
    if target.parent != _private_directory() or not target.name.startswith("draft-"):
        raise WorkspaceError("Creator versions require the private drafts directory")
    parsed = recipes.parse(payload)
    digest = review._semantic_hash(review._manifest(parsed))
    if target.exists() or target.is_symlink():
        raise WorkspaceError("Creator version already exists; nothing was overwritten")
    try:
        creator_history.write(target, digest, kind=kind, parent=parent)
    except creator_history.HistoryError as exc:
        raise WorkspaceError(str(exc)) from exc
    # This is a no-replace link. If publication fails, the intent is retained
    # for recovery inspection, and the previous version is still usable.
    recipes._write_private_new(target, payload)
    dirfd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)
    info = open_draft(target)
    if info.semantic_sha256 != digest:
        raise WorkspaceError("Published version failed its fingerprint verification")
    return info


def previous_version(info: DraftInfo) -> DraftInfo | None:
    """Follow one verified parent receipt, including after restarting Creator."""
    current = open_draft(info.path)
    if current.semantic_sha256 != info.semantic_sha256:
        raise WorkspaceError("Creator draft changed since it was opened")
    if info.path.parent != _private_directory():
        raise WorkspaceError("Creator history is only available for private workspace drafts")
    try:
        receipt = creator_history.read(info.path, current.semantic_sha256)
    except creator_history.HistoryError as exc:
        raise WorkspaceError(str(exc)) from exc
    if receipt is None or receipt["parent"] is None:
        return None
    ancestor = open_draft(info.path.parent / receipt["parent"]["filename"])
    if ancestor.semantic_sha256 != receipt["parent"]["semantic_sha256"]:
        raise WorkspaceError("An earlier Creator version was modified; history cannot be trusted")
    return ancestor


def version_history(info: DraftInfo) -> list[DraftInfo]:
    """Newest first; validate each link with a strict 64-version traversal bound."""
    chain: list[DraftInfo] = []
    seen: set[Path] = set()
    current: DraftInfo | None = info
    while current is not None and len(chain) < creator_history.MAX_HISTORY_DEPTH:
        if current.path in seen:
            raise WorkspaceError("Creator version history contains a cycle")
        seen.add(current.path)
        chain.append(open_draft(current.path))
        current = previous_version(current)
    return chain


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
        _parsed, payload = recipes._prepare_template(source=template, recipe_id=recipe_id,
                                                     name=title, schema_version=11)
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
    return _publish_version(target, payload, "create")


def installed_editable() -> list[dict[str, str | int]]:
    """List validated installed rices that the current Creator can edit."""
    found = []
    for recipe, _ in recipes.imported_recipes():
        if recipe.schema_version >= 10:
            found.append({"id": recipe.recipe_id, "name": recipe.name,
                          "schema_version": recipe.schema_version,
                          "semantic_sha256": review._semantic_hash(review._manifest(recipe))})
    return found


def create_draft_from_installed(recipe_id: str, *, expected_sha256: str) -> DraftInfo:
    """Fork an installed recipe into an editable, never-applied private draft.

    The fingerprint pins the choice displayed by the GUI, preventing a changed
    installed file from being silently copied during a delayed confirmation.
    """
    if (not isinstance(recipe_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", recipe_id)
            or recipe_id in recipes.BUILTINS):
        raise WorkspaceError("Choose a private installed rice, not a built-in or path")
    source = recipes._private_recipe_dir(create=False) / f"{recipe_id}.json"
    raw = recipes._read_import_source(source)
    parsed = recipes.parse(raw)
    digest = review._semantic_hash(review._manifest(parsed))
    if parsed.recipe_id != recipe_id or digest != expected_sha256:
        raise WorkspaceError("Installed rice changed since selection. Reopen the list")
    if parsed.schema_version < 10:
        raise WorkspaceError("Creator editing requires recipe schema v10 or newer")
    # Resolve referenced data-only assets now, before publishing a draft that
    # cannot render or be exported again.
    pack._wallpaper_identity(parsed)
    pack._visual_assets(parsed)
    manifest = json.loads(raw)
    manifest["id"] = f"creator-{secrets.token_hex(6)}"
    payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    recipes.parse(payload)
    return _publish_version(_new_file(_private_directory()), payload, "import")


def _revision_patch(source: Path, changes: dict[str, Any], *, expected_sha256: str
                    ) -> tuple[Path, bytes]:
    """Validate a workspace revision and encode one bounded, data-only patch."""
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
    return folder, payload


@contextmanager
def _temporary_edit(folder: Path, payload: bytes):
    """Keep the owner-only edit input only for the validation/write call."""
    descriptor, patch_name = tempfile.mkstemp(prefix=".creator-edit-", suffix=".json", dir=folder)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
        yield Path(patch_name)
    finally:
        os.unlink(patch_name)


def preview_revision(source: Path, changes: dict[str, Any], *, expected_sha256: str
                     ) -> dict[str, Any]:
    """Return the exact full-parser diff, with no saved version or desktop effect."""
    folder, payload = _revision_patch(source, changes, expected_sha256=expected_sha256)
    with _temporary_edit(folder, payload) as patch_file:
        return drafts.check_edit(recipe_token=str(source), edit_source=patch_file,
                                 expected_sha256=expected_sha256)


def save_revision(source: Path, changes: dict[str, Any], *, expected_sha256: str,
                  expected_draft_sha256: str | None = None
                  ) -> tuple[DraftInfo, list[dict[str, Any]]]:
    """Create a new private version; reject changes since a reviewed preflight."""
    if (expected_draft_sha256 is not None and
            (type(expected_draft_sha256) is not str or
             re.fullmatch(r"[a-f0-9]{64}", expected_draft_sha256) is None)):
        raise drafts.DraftError("Expected draft fingerprint must be 64 lowercase hex characters",
                                code="invalid_draft_fingerprint")
    folder, payload = _revision_patch(source, changes, expected_sha256=expected_sha256)
    with _temporary_edit(folder, payload) as patch_file:
        result, revised_payload = drafts._prepare_edit(
            recipe_token=str(source), edit_source=patch_file, expected_sha256=expected_sha256)
    if (expected_draft_sha256 is not None and
            result["draft_semantic_sha256"] != expected_draft_sha256):
        raise drafts.DraftError("Proposed draft changed since preflight; inspect it again",
                                code="draft_changed")
    destination = _new_file(folder)
    saved = _publish_version(destination, revised_payload, "save",
                             parent=(source.name, expected_sha256))
    return saved, result["changes"]


def fork_version(info: DraftInfo) -> DraftInfo:
    """Copy a reviewed immutable draft to a fresh ID, keeping its full layout.

    Useful when an earlier version of the same ID is already installed. The
    installed recipe and the source draft are never replaced or modified.
    """
    folder = _private_directory()
    if info.path.parent != folder:
        raise WorkspaceError("Open a draft from the private Creator workspace")
    current = open_draft(info.path)
    if current.semantic_sha256 != info.semantic_sha256:
        raise WorkspaceError("Draft changed on disk. Reopen before forking")
    raw = recipes._read_import_source(info.path)
    parsed = recipes.parse(raw)
    if review._semantic_hash(review._manifest(parsed)) != info.semantic_sha256:
        raise WorkspaceError("Draft changed during copy. Reopen before forking")
    manifest = json.loads(raw)
    manifest["id"] = f"creator-{secrets.token_hex(6)}"
    payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    recipes.parse(payload)
    target = _new_file(folder)
    return _publish_version(target, payload, "fork",
                            parent=(info.path.name, info.semantic_sha256))


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
    return _publish_version(target, payload, "upgrade",
                            parent=(info.path.name, info.semantic_sha256))


def export_draft(info: DraftInfo, destination: Path) -> dict[str, Any]:
    if open_draft(info.path).semantic_sha256 != info.semantic_sha256:
        raise WorkspaceError("Draft changed on disk. Reload before exporting")
    recipe = recipes.load(str(info.path))
    declared = (creator_assets.entry(recipe.wallpaper).provenance
                if assets.ASSET_ID.fullmatch(recipe.wallpaper or "") else None)
    return pack.export_pack(str(info.path), destination, wallpaper_provenance=declared)
