"""Safe, bounded component edits against real RicePlate panel recipes.

The same strict recipe parser validates the resulting runtime JSON. Drafts are
never installed or selected by the editor; an explicit nested preview remains
necessary before any session-related action.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from . import recipes, review
from .creator_contract import EDIT_VERSION, EDITABLE_PATHS, MAX_EDIT_BYTES, MAX_OPERATIONS


class DraftError(recipes.RecipeError):
    """An invalid, unsupported or unsafe offline edit; no draft published."""

    def __init__(self, message: str, *, code: str = "invalid_edit", path: str | None = None):
        super().__init__(message)
        self.code = code
        # Only static, allowlisted property paths can enter machine output.
        self.path = path if path in EDITABLE_PATHS else None


def _allowed_value(path: str, value: Any, schema_version: int) -> bool:
    """Reject nested/oversized executable-looking content before serialization."""
    if path.startswith("/panel/sections/"):
        return (type(value) is list and len(value) <= 7
                and all(type(item) is str and item in recipes.WIDGETS for item in value))
    if path.startswith(("/panel/layout/", "/responsive/compact_layout/")):
        if type(value) is not list or len(value) > recipes.MAX_LAYOUT_ROOTS:
            return False
        try:
            counts = [0, 0]
            widgets: list[str] = []
            actions: dict[str, str] = {}
            for node in value:
                recipes._parse_layout_node(node, 1, counts, widgets, actions,
                                           schema_version=schema_version)
        except recipes.RecipeError:
            return False
        return True
    if path == "/menu/groups":
        try:
            recipes._parse_menu({"title": "Safe", "groups": value}, schema_version=6)
        except recipes.RecipeError:
            return False
        return True
    if path == "/menu/title":
        return recipes._safe_label(value, 32)
    if path == "/menu/presentation":
        return type(value) is str and value in ("tabs", "sidebar")
    if path == "/desktop/wallpaper":
        return type(value) is str and value in recipes.WALLPAPERS
    if path == "/desktop/icons":
        try:
            recipes._parse_desktop_icons(value)
        except recipes.RecipeError:
            return False
        return True
    if path.startswith("/composition/"):
        if schema_version < 8:
            return False
        baseline = {"widgets": [], "window_region": {"x": 0, "y": 0,
                    "width": 100, "height": 100}, "compact_hide_widgets": []}
        baseline[path.removeprefix("/composition/")] = value
        if path == "/composition/compact_hide_widgets":
            return (type(value) is list and len(value) <= recipes.MAX_DESKTOP_WIDGETS
                    and all(type(item) is str for item in value)
                    and len(set(value)) == len(value))
        try:
            recipes._parse_composition(baseline, schema_version=schema_version)
        except recipes.RecipeError:
            return False
        return True
    if path == "/responsive/compact_max_width":
        return type(value) is int and 480 <= value <= 1440
    if path in ("/tokens/label_padding", "/tokens/task_radius"):
        maximum = 16 if path.endswith("label_padding") else 12
        return type(value) is int and 0 <= value <= maximum
    if path == "/panel/height":
        return type(value) is int and 28 <= value <= 64
    if path.startswith("/panel/metrics/"):
        field = path.rsplit("/", 1)[-1]
        lower, upper = recipes.METRIC_LIMITS[recipes.METRIC_FIELDS.index(field)]
        return type(value) is int and lower <= value <= upper
    if path == "/panel/position":
        return type(value) is str and value in ("top", "bottom")
    if path.startswith("/colors/"):
        return type(value) is str and re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None
    return (type(value) is str and 1 <= len(value) <= 60
            and not any(unicodedata.category(character) == "Cc" for character in value))


def _parse_edit(payload: bytes, *, schema_version: int) -> list[tuple[str, Any]]:
    if len(payload) > MAX_EDIT_BYTES:
        raise DraftError("Draft edit exceeds the 16 KiB limit", code="edit_too_large")
    try:
        data = json.loads(payload.decode("utf-8"),
                          object_pairs_hook=recipes._object_without_duplicates)
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise DraftError("Invalid draft edit JSON", code="malformed_json") from exc
    if (not isinstance(data, dict) or set(data) != {"edit_version", "operations"}
            or type(data["edit_version"]) is not int or data["edit_version"] != EDIT_VERSION):
        raise DraftError("Unsupported draft edit schema", code="unsupported_edit_schema")
    operations = data["operations"]
    if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_OPERATIONS:
        raise DraftError("Draft needs 1–16 bounded set operations", code="invalid_operation_count")
    changes: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for item in operations:
        if (not isinstance(item, dict) or set(item) != {"op", "path", "value"}
                or item["op"] != "set" or type(item["path"]) is not str
                or item["path"] not in EDITABLE_PATHS or item["path"] in seen):
            raise DraftError("Draft contains an unsupported or duplicate edit operation",
                             code="unsupported_operation")
        if not _allowed_value(item["path"], item["value"], schema_version):
            raise DraftError("Value is outside the supported component property range or type",
                             code="invalid_value", path=item["path"])
        seen.add(item["path"])
        changes.append((item["path"], item["value"]))
    return changes


def create_edit(*, recipe_token: str, edit_source: Path, destination: Path) -> dict[str, Any]:
    """Validate data edits and atomically create a new owner-only recipe.

    The input patch is an owner-controlled .json file, allowed to be 0644;
    the source recipe retains the existing 0600 requirement. Neither the
    source nor next-login selection is modified, including on any failure.
    """
    if not destination.is_absolute() or destination.suffix != ".json":
        raise DraftError("Draft destination must be an absolute .json file path",
                         code="invalid_output")
    try:
        original = recipes.load(recipe_token)
        raw = recipes._read_import_source(edit_source)
        operations = _parse_edit(raw, schema_version=original.schema_version)
    except recipes.RecipeError as exc:
        if isinstance(exc, DraftError):
            raise
        raise DraftError("Draft source recipe or edit file is unavailable or unsafe",
                         code="unavailable_source") from exc

    before = review._manifest(original)
    modified = json.loads(json.dumps(before))
    for path, value in operations:
        if path.startswith("/panel/layout/") and modified["schema_version"] < 3:
            raise DraftError("Nested layout requires a schema-v3+ source recipe",
                             code="unsupported_property_for_schema", path=path)
        if path.startswith("/panel/sections/") and modified["schema_version"] >= 3:
            raise DraftError("Schema-v3+ uses panel layout, not legacy sections",
                             code="unsupported_property_for_schema", path=path)
        if path.startswith("/panel/metrics/") and modified["schema_version"] < 2:
            raise DraftError("Panel metrics require a schema-v2+ source recipe",
                             code="unsupported_property_for_schema", path=path)
        if path.startswith(("/menu/", "/desktop/", "/tokens/", "/responsive/")) \
                and modified["schema_version"] < 4:
            raise DraftError("Shell components require a schema-v4+ source recipe",
                             code="unsupported_property_for_schema", path=path)
        if path == "/menu/presentation" and modified["schema_version"] < 6:
            raise DraftError("Menu presentation requires a schema-v6 source recipe",
                             code="unsupported_property_for_schema", path=path)
        if path == "/desktop/icons" and modified["schema_version"] < 5:
            raise DraftError("Desktop icons require a schema-v5+ source recipe",
                             code="unsupported_property_for_schema", path=path)
        if path.startswith("/composition/") and modified["schema_version"] < 8:
            raise DraftError("Desktop composition requires a schema-v8 source recipe",
                             code="unsupported_property_for_schema", path=path)
        parts = path.lstrip("/").split("/")
        current = modified
        for part in parts[:-1]:
            current = current[part]
        current[parts[-1]] = value
    payload = (json.dumps(modified, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    try:
        updated = recipes.parse(payload)
    except recipes.RecipeError as exc:
        raise DraftError("Edited composition duplicates a widget or lacks required launcher/tasks",
                         code="invalid_composition") from exc
    after = review._manifest(updated)
    changes = review.semantic_changes(before, after)
    if not changes:
        raise DraftError("Draft edit must change at least one supported property", code="no_effect")
    try:
        recipes._write_private_new(destination, payload)
    except OSError as exc:
        raise DraftError("Could not safely create draft without overwriting a file",
                         code="output_unavailable") from exc
    return {
        "edit_version": EDIT_VERSION,
        "ok": True,
        "created": True,
        "applied": False,
        "recipe_id": updated.recipe_id,
        "source_semantic_sha256": review._semantic_hash(before),
        "draft_semantic_sha256": review._semantic_hash(after),
        "changes": changes,
    }


def invalid_edit(error: DraftError | None = None) -> dict[str, Any]:
    """Path-free except a known property pointer; stable agent diagnostics."""
    detail: dict[str, Any] = {
        "code": error.code if error else "invalid_edit",
        "message": str(error) if error else "Invalid or unsafe draft edit input",
    }
    if error and error.path:
        detail["path"] = error.path
    return {
        "edit_version": EDIT_VERSION,
        "ok": False,
        "created": False,
        "applied": False,
        "error": detail,
    }
