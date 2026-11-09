"""Rice Creator 0.7: bounded offline image hints and reviewable mapping proposals.

Images stay private. Neither heuristics nor external proposal JSON are executable
instructions: every proposed change goes through the existing draft validator and
the full recipe parser before it may reach an unsaved Creator working copy.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import re
from collections import Counter
from typing import Any

from . import creator_reference, drafts, recipes

VERSION = 1
MAX_MAPPING_BYTES = 24 * 1024
MAX_SUGGESTIONS = 12
MAPPABLE_PATHS = frozenset({
    "/panel/position", "/panel/height", "/colors/background",
    "/colors/foreground", "/colors/active", "/menu/presentation",
    "/appearance/item_spacing", "/tokens/label_padding",
    "/panel/layout/start", "/panel/layout/center", "/panel/layout/end",
})
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class MappingError(ValueError):
    """Untrusted suggestion, stale reference or unsupported image."""


def ensure_current_reference(recipe_id: str, expected_sha256: str) -> None:
    """Fail closed if an owner-private reference was replaced outside this UI."""
    try:
        current = creator_reference.selected(recipe_id)
    except creator_reference.ReferenceError as exc:
        raise MappingError("Selected reference changed or failed integrity verification") from exc
    if current is None or current.sha256 != expected_sha256:
        raise MappingError("Selected reference changed; load or analyze it again")


def contract() -> dict[str, object]:
    return {
        "mapping_version": VERSION,
        "format": "owner-reviewed-data-only-json",
        "required_fields": ["mapping_version", "source", "reference_sha256",
                            "recipe_sha256", "reference_size", "regions", "suggestions", "notes"],
        "sources": ["offline", "external"],
        "suggestion_fields": ["path", "value", "confidence", "evidence"],
        "allowed_paths": sorted(MAPPABLE_PATHS),
        "max_suggestions": MAX_SUGGESTIONS,
        "max_json_bytes": MAX_MAPPING_BYTES,
        "privacy": "Reference PNG is not embedded or uploaded; owner shares it separately if desired",
        "trust": "All source labels and confidence values are untrusted; runtime validation is mandatory",
        "import_origin": "every file import is reclassified as external and starts unchecked",
        "confidence_interpretation": "unvalidated heuristic strength or external claim, never a calibrated probability",
        "effect": "suggestions only; user must select and Save version; never applies a rice",
        "automatic_menu_or_component_recognition": False,
    }


def _rgb_distance(one: tuple[int, int, int], two: tuple[int, int, int]) -> int:
    return max(abs(a - b) for a, b in zip(one, two))


def _bucket(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(channel // 16 for channel in rgb)


def _row_color(image, y: int) -> tuple[tuple[int, int, int], float]:
    width = image.width
    samples = [image.getpixel((min(width - 1, (x * width) // 96), y))
               for x in range(96)]
    groups = Counter(_bucket(pixel) for pixel in samples)
    dominant, count = groups.most_common(1)[0]
    matching = [pixel for pixel in samples if _bucket(pixel) == dominant]
    color = tuple(sorted(pixel[i] for pixel in matching)[len(matching) // 2]
                  for i in range(3))
    return color, count / len(samples)


def _strip_content_fraction(image, edge: str, height: int,
                            background: tuple[int, int, int]) -> tuple[int, int]:
    """Count visible contrasting panel marks, not just a wallpaper color band."""
    y0 = 3 if edge == "top" else image.height - height + 2
    y1 = height - 2 if edge == "top" else image.height - 3
    occupied = sampled = 0
    for y in range(y0, y1, 2):
        for index in range(128):
            pixel = image.getpixel(((index * image.width) // 128, y))
            sampled += 1
            occupied += _rgb_distance(pixel, background) > 65
    return occupied, sampled


def _scan_edge(image, edge: str) -> dict[str, Any] | None:
    if image.height < 128 or image.width < 96:
        return None
    base_y = 5 if edge == "top" else image.height - 6
    color, uniformity = _row_color(image, base_y)
    if uniformity < 0.62:
        return None
    best = None
    for thickness in range(28, min(64, image.height // 3) + 1):
        offset = thickness if edge == "top" else image.height - 1 - thickness
        # The boundary must be immediately after the proposed band; accepting
        # merely 80% stable interior rows can overestimate by several pixels.
        boundary = [_row_color(image, thickness - step if edge == "top" else
                               image.height - thickness - 1 + step)
                    for step in (1, 2, 3)]
        if any(_rgb_distance(color, row_color) >= 30 or portion < 0.48
               for row_color, portion in boundary):
            continue
        outside = [_row_color(image, offset + n if edge == "top" else offset - n)
                   for n in range(3)]
        if any(_rgb_distance(color, outside_color) < 44
               for outside_color, _ in outside):
            continue
        inside = [_row_color(image, p if edge == "top" else image.height - 1 - p)
                  for p in range(5, thickness, 4)]
        stable = sum(_rgb_distance(color, item[0]) < 30 and item[1] >= 0.48
                     for item in inside) / len(inside)
        contrast = min(_rgb_distance(color, item[0]) for item in outside)
        if stable < 0.79:
            continue
        occupied, sampled = _strip_content_fraction(image, edge, thickness, color)
        # A uniform decorative band has no evidence of real controls. Dense
        # photo texture is also insufficient evidence of a panel foreground.
        if occupied < max(3, sampled // 1000) or occupied > sampled // 4:
            continue
        confidence = round(min(0.96, 0.55 + stable * 0.25 +
                               min(contrast, 150) / 150 * 0.15), 2)
        best = {"edge": edge, "height": thickness, "color": color,
                "confidence": confidence, "uniformity": round(uniformity, 2),
                "contrast": contrast, "content_percent": round(100 * occupied / sampled, 1)}
        break
    return best


def _panel_palette(image, panel: dict) -> tuple[str | None, str | None]:
    """Collect only visually distinct visible text/accent candidates, not guesses."""
    height = panel["height"]
    rows = range(3, height - 2, 2) if panel["edge"] == "top" else (
        range(image.height - height + 2, image.height - 3, 2))
    pixels = [image.getpixel(((x * image.width) // 128, y))
              for y in rows for x in range(128)]
    background = panel["color"]
    frequencies = Counter(_bucket(pixel) for pixel in pixels
                          if _rgb_distance(pixel, background) > 65)
    foreground = accent = None
    for key, count in frequencies.most_common(20):
        if count < max(9, len(pixels) // 240) or count > len(pixels) // 4:
            continue
        rgb = tuple(min(255, channel * 16 + 8) for channel in key)
        saturation = max(rgb) - min(rgb)
        if foreground is None and saturation <= 35 and _contrast(rgb, background) >= 4.5:
            foreground = _hex(rgb)
        if accent is None and saturation >= 85 and _rgb_distance(rgb, background) >= 95:
            accent = _hex(rgb)
    return foreground, accent


def _contrast(a, b) -> float:
    def luminance(rgb):
        channels = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                    for c in (v / 255 for v in rgb)]
        return sum(x * weight for x, weight in zip(channels, (0.2126, 0.7152, 0.0722)))
    one, two = sorted((luminance(a), luminance(b)))
    return (two + 0.05) / (one + 0.05)


def _hex(color) -> str:
    return "#" + "".join(f"{channel:02x}" for channel in color)


def analyze(data: bytes, *, reference_sha256: str, recipe_sha256: str) -> dict[str, Any]:
    """Infer conservative panel/palette hints from verified local screenshot bytes."""
    if (type(data) is not bytes or type(reference_sha256) is not str
            or not _SHA.fullmatch(reference_sha256)
            or type(recipe_sha256) is not str or not _SHA.fullmatch(recipe_sha256)
            or hashlib.sha256(data).hexdigest() != reference_sha256):
        raise MappingError("Reference identity or screenshot bytes changed")
    width, height = creator_reference._image_size(data)
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as source:
            # All column/row sampling stays O(1) per target row and works on
            # RGB, avoiding decompression-sized arrays in algorithmic state.
            image = source.convert("RGB")
        possibilities = [value for edge in ("top", "bottom")
                         if (value := _scan_edge(image, edge)) is not None]
        notes: list[str] = []
        suggestions: list[dict[str, Any]] = []
        regions: list[dict[str, Any]] = []
        if not possibilities:
            notes.append("No reliable full-width 28–64 px panel edge detected. Nothing inferred.")
        else:
            possibilities.sort(key=lambda item: item["confidence"], reverse=True)
            winner = possibilities[0]
            if (len(possibilities) > 1 and
                    possibilities[1]["confidence"] >= winner["confidence"] - 0.07):
                notes.append("Top and bottom bands are ambiguous; no panel mapping inferred.")
            else:
                edge, thickness = winner["edge"], winner["height"]
                regions.append({"kind": "panel", "x": 0,
                                "y": 0 if edge == "top" else height - thickness,
                                "width": width, "height": thickness,
                                "confidence": winner["confidence"]})
                evidence = (f"Full-width {edge} strip; sampled color stability "
                            f"{winner['uniformity']:.0%}, boundary contrast "
                            f"{winner['contrast']} RGB levels, contrasting marks "
                            f"{winner['content_percent']}%")
                suggestions.extend((
                    {"path": "/panel/position", "value": edge,
                     "confidence": winner["confidence"], "evidence": evidence},
                    {"path": "/panel/height", "value": thickness,
                     "confidence": winner["confidence"], "evidence": evidence},
                    {"path": "/colors/background", "value": _hex(winner["color"]),
                     "confidence": round(winner["confidence"] * 0.91, 2),
                     "evidence": "Most common sampled color in detected panel strip"},
                ))
                foreground, accent = _panel_palette(image, winner)
                if foreground:
                    suggestions.append({"path": "/colors/foreground", "value": foreground,
                                        "confidence": 0.54,
                                        "evidence": "Contrasting neutral pixels in panel; may be text or icons"})
                if accent:
                    suggestions.append({"path": "/colors/active", "value": accent,
                                        "confidence": 0.39,
                                        "evidence": "Saturated panel pixels; may be an icon, not accent"})
        notes.append("Menu identity, panel widgets, layout lanes and spacing are not inferred "
                     "from screenshot pixels; external suggestions require separate review.")
        return {"mapping_version": VERSION, "source": "offline",
                "reference_sha256": reference_sha256, "recipe_sha256": recipe_sha256,
                "reference_size": {"width": width, "height": height},
                "regions": regions, "suggestions": suggestions, "notes": notes}
    except (OSError, ValueError) as exc:
        raise MappingError("Could not inspect the selected reference") from exc


def _identity(mapping: dict, *, reference_sha256: str, recipe_sha256: str,
              size: tuple[int, int]) -> None:
    if (mapping.get("reference_sha256") != reference_sha256
            or mapping.get("recipe_sha256") != recipe_sha256
            or mapping.get("reference_size") != {"width": size[0], "height": size[1]}):
        raise MappingError("Mapping targets another screenshot or saved draft; analyze again")


def _validate_edit(changes: dict[str, Any], manifest: dict) -> None:
    if not changes:
        return
    payload = {"edit_version": drafts.EDIT_VERSION, "operations": [
        {"op": "set", "path": path, "value": value} for path, value in changes.items()]}
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        definitions = recipes._parse_components(manifest["components"])
        drafts._parse_edit(encoded, schema_version=manifest["schema_version"],
                           components=definitions)
        candidate = copy.deepcopy(manifest)
        for path, value in changes.items():
            cursor = candidate
            parts = path.lstrip("/").split("/")
            for part in parts[:-1]:
                cursor = cursor[part]
            cursor[parts[-1]] = copy.deepcopy(value)
        recipes.parse(json.dumps(candidate, ensure_ascii=False).encode("utf-8"))
    except (drafts.DraftError, recipes.RecipeError, KeyError, TypeError, ValueError,
            UnicodeError, RecursionError) as exc:
        raise MappingError(f"Suggested recipe edits are invalid: {exc}") from exc


def validate(raw: bytes | dict, *, reference_sha256: str, recipe_sha256: str,
             size: tuple[int, int], manifest: dict) -> dict[str, Any]:
    """Validate a wholly untrusted AI/offline proposal without altering files."""
    if type(raw) is bytes:
        if len(raw) > MAX_MAPPING_BYTES:
            raise MappingError("Mapping exceeds the 24 KiB limit")
        try:
            mapping = json.loads(raw.decode("utf-8"),
                                 object_pairs_hook=recipes._object_without_duplicates)
        except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
            raise MappingError("Malformed mapping JSON") from exc
    else:
        mapping = copy.deepcopy(raw)
        try:
            if len(json.dumps(mapping).encode("utf-8")) > MAX_MAPPING_BYTES:
                raise MappingError("Mapping exceeds the 24 KiB limit")
        except (ValueError, TypeError, RecursionError) as exc:
            raise MappingError("Malformed mapping data") from exc
    fields = {"mapping_version", "source", "reference_sha256", "recipe_sha256",
              "reference_size", "regions", "suggestions", "notes"}
    if (type(mapping) is not dict or set(mapping) != fields
            or type(mapping["mapping_version"]) is not int
            or mapping["mapping_version"] != VERSION
            or mapping["source"] not in ("offline", "external")
            or type(mapping["reference_sha256"]) is not str
            or type(mapping["recipe_sha256"]) is not str
            or not _SHA.fullmatch(mapping["reference_sha256"])
            or not _SHA.fullmatch(mapping["recipe_sha256"])):
        raise MappingError("Unsupported mapping contract or fields")
    _identity(mapping, reference_sha256=reference_sha256,
              recipe_sha256=recipe_sha256, size=size)
    if (type(mapping["notes"]) is not list or len(mapping["notes"]) > 6
            or any(type(note) is not str or len(note) > 190 or
                   any(ord(char) < 32 for char in note) for note in mapping["notes"])):
        raise MappingError("Notes must be short, printable evidence")
    regions = mapping["regions"]
    if type(regions) is not list or len(regions) > 8:
        raise MappingError("Too many suggested regions")
    for region in regions:
        if (type(region) is not dict or set(region) !=
                {"kind", "x", "y", "width", "height", "confidence"}
                or region["kind"] not in ("panel", "menu", "desktop", "unknown")
                or any(type(region[key]) is not int for key in ("x", "y", "width", "height"))
                or min(region["x"], region["y"]) < 0
                or min(region["width"], region["height"]) <= 0
                or region["x"] + region["width"] > size[0]
                or region["y"] + region["height"] > size[1]
                or not _valid_confidence(region["confidence"])):
            raise MappingError("Region outside reference image or unsupported kind")
    items = mapping["suggestions"]
    if type(items) is not list or len(items) > MAX_SUGGESTIONS:
        raise MappingError("Mapping must have at most 12 suggested changes")
    changes: dict[str, Any] = {}
    for item in items:
        if (type(item) is not dict or set(item) != {"path", "value", "confidence", "evidence"}
                or type(item["path"]) is not str or item["path"] not in MAPPABLE_PATHS
                or item["path"] in changes
                or not _valid_confidence(item["confidence"])
                or type(item["evidence"]) is not str or not 1 <= len(item["evidence"]) <= 190
                or any(ord(char) < 32 for char in item["evidence"])):
            raise MappingError("Unsupported, duplicate or unexplained mapping suggestion")
        changes[item["path"]] = item["value"]
    _validate_edit(changes, manifest)
    return mapping


def import_proposals(raw: bytes, *, reference_sha256: str, recipe_sha256: str,
                     size: tuple[int, int], manifest: dict) -> dict[str, Any]:
    """Disk-sourced JSON is always external, even if it claims offline origin.

    Only the in-process analyzer may produce trusted offline suggestions.
    Confidence and provenance fields in a user-editable file have no authority.
    """
    mapping = validate(raw, reference_sha256=reference_sha256,
                       recipe_sha256=recipe_sha256, size=size, manifest=manifest)
    mapping["source"] = "external"
    return mapping


def _valid_confidence(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def selected_changes(mapping: dict, paths: set[str], *, reference_sha256: str,
                     recipe_sha256: str, size: tuple[int, int], manifest: dict) -> dict[str, Any]:
    """Recheck identity AND the chosen combination before unsaved authoring."""
    checked = validate(mapping, reference_sha256=reference_sha256,
                       recipe_sha256=recipe_sha256, size=size, manifest=manifest)
    known = {item["path"]: item["value"] for item in checked["suggestions"]}
    if type(paths) is not set or not paths or not paths <= known.keys():
        raise MappingError("Select at least one actual proposed change")
    changes = {path: known[path] for path in sorted(paths)}
    _validate_edit(changes, manifest)
    return changes
