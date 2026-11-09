"""Rice Creator reference regions and real-pixel diagnostics (0.8–0.9).

This module never edits a recipe or a screenshot. Regions are explicit user
annotations, not guesses about visible controls or functional correctness.
"""

from __future__ import annotations

import hashlib
import io
import re
from typing import Any

from . import creator_reference, visual_qa

VERSION = 1
MAX_REGIONS = 8
KINDS = ("panel", "menu", "desktop", "unknown")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class RegionError(ValueError):
    """Unsafe region geometry, stale reference or invalid comparison input."""


def contract() -> dict[str, Any]:
    return {
        "region_report_version": VERSION,
        "ui": "ricebowl creator (GTK; not a separate de CLI command)",
        "kinds": list(KINDS), "max_regions": MAX_REGIONS,
        "rect_fields": ["kind", "x", "y", "width", "height"],
        "coordinates": "source screenshot pixels; no automatic scaling",
        "mouse_selection": "0.9 GTK reference viewer; fitted pointer bounds become original source pixels",
        "policy": {"pixel_threshold": [0, 255], "tolerance_radius": [0, 1, 2]},
        "identity": ["reference_sha256", "capture_sha256", "recipe_sha256"],
        "effect": "private in-memory read-only diagnostics; optional owner-exported JSON",
        "accuracy": "raw and raster-tolerated pixel errors; no perceptual/functional score",
        "privacy": "no screenshot pixels in JSON; source images never uploaded",
        "correction_cycle": {"iteration_version": 1, "max_measurements": 12,
                             "requires": "same reference, regions, dimensions and pixel policy",
                             "result": "per-region changed-pixel percentage-point delta"},
    }


def validate(regions: list[dict], *, size: tuple[int, int]) -> list[dict]:
    """Accept up to eight bounded, non-duplicated user-defined rectangles."""
    width, height = size
    if (type(width) is not int or type(height) is not int or
            not 1 <= width <= 8192 or not 1 <= height <= 8192 or
            width * height > creator_reference.MAX_PIXELS or
            type(regions) is not list or len(regions) > MAX_REGIONS):
        raise RegionError("Invalid image size or more than eight reference regions")
    reviewed = []
    seen = set()
    for region in regions:
        if (type(region) is not dict or set(region) !=
                {"kind", "x", "y", "width", "height"} or
                type(region["kind"]) is not str or region["kind"] not in KINDS or
                any(type(region[key]) is not int for key in ("x", "y", "width", "height")) or
                min(region["x"], region["y"]) < 0 or
                min(region["width"], region["height"]) <= 0 or
                region["x"] + region["width"] > width or
                region["y"] + region["height"] > height):
            raise RegionError("Region must be a known kind and fit inside the reference")
        identity = (region["kind"], region["x"], region["y"],
                    region["width"], region["height"])
        if identity in seen:
            raise RegionError("Duplicate reference region")
        seen.add(identity)
        reviewed.append(region.copy())
    if sum(region["width"] * region["height"] for region in reviewed) > 2 * width * height:
        raise RegionError("Annotated area exceeds twice the image; choose smaller regions")
    return reviewed


def _image(data: bytes, *, expected_sha256: str | None = None):
    if type(data) is not bytes or len(data) > creator_reference.MAX_PNG_BYTES:
        raise RegionError("Expected bounded PNG bytes")
    if expected_sha256 is not None and (type(expected_sha256) is not str or
            not _SHA.fullmatch(expected_sha256) or
            hashlib.sha256(data).hexdigest() != expected_sha256):
        raise RegionError("Reference screenshot changed; select it again")
    try:
        from PIL import Image
        creator_reference._image_size(data)
        with Image.open(io.BytesIO(data)) as source:
            return source.convert("RGB")
    except (creator_reference.ReferenceError, OSError, ValueError) as exc:
        raise RegionError("Cannot read the verified PNG screenshot") from exc


def annotated_view(reference: bytes, *, reference_sha256: str,
                   regions: list[dict]) -> bytes:
    """Draw numbered region outlines on a copy of the verified private PNG."""
    image = _image(reference, expected_sha256=reference_sha256)
    reviewed = validate(regions, size=image.size)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(image)
    colors = {"panel": "#2fe5ac", "menu": "#f9bd49",
              "desktop": "#64b5ff", "unknown": "#eaa6f2"}
    for index, region in enumerate(reviewed, start=1):
        x, y, w, h = (region[key] for key in ("x", "y", "width", "height"))
        color = colors[region["kind"]]
        draw.rectangle((x, y, x + w - 1, y + h - 1), outline=color, width=2)
        draw.text((x + 3, y + 3), str(index), fill=color, stroke_width=1,
                  stroke_fill="#000000")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def inspect(reference: bytes, actual: bytes, *, reference_sha256: str,
            recipe_sha256: str, regions: list[dict], threshold: int = 24,
            tolerance_radius: int = 1) -> dict[str, Any]:
    """Return only geometry and pixel errors for explicitly selected regions.

    The tolerance calculation includes a radius-wide neighborhood around each
    rectangle, so edge pixels are measured like the full-frame QA engine.
    """
    if (type(recipe_sha256) is not str or not _SHA.fullmatch(recipe_sha256) or
            type(threshold) is not int or not 0 <= threshold <= 255 or
            type(tolerance_radius) is not int or tolerance_radius not in (0, 1, 2)):
        raise RegionError("Invalid recipe identity or pixel comparison policy")
    before = _image(reference, expected_sha256=reference_sha256)
    after = _image(actual)
    if before.size != after.size:
        raise RegionError("Native capture and reference resolutions must match exactly")
    reviewed = validate(regions, size=before.size)
    if not reviewed:
        raise RegionError("Add at least one region for a focused comparison")
    from PIL import ImageChops
    entries = []
    for index, region in enumerate(reviewed, start=1):
        x, y, w, h = (region[key] for key in ("x", "y", "width", "height"))
        box = (x, y, x + w, y + h)
        raw = ImageChops.difference(before.crop(box), after.crop(box))
        if tolerance_radius:
            padding = tolerance_radius
            padded = (max(0, x - padding), max(0, y - padding),
                      min(before.width, x + w + padding),
                      min(before.height, y + h + padding))
            tolerant = visual_qa._tolerant_difference(before.crop(padded),
                                                      after.crop(padded), padding)
            local = (x - padded[0], y - padded[1],
                     x - padded[0] + w, y - padded[1] + h)
            tolerant = tolerant.crop(local)
        else:
            tolerant = raw
        entries.append({"number": index, "kind": region["kind"],
                        "rect": {key: region[key] for key in ("x", "y", "width", "height")},
                        **visual_qa._metrics(raw, threshold=threshold),
                        "tolerance": visual_qa._metrics(tolerant, threshold=threshold)})
    return {"region_report_version": VERSION,
            "reference_sha256": reference_sha256,
            "capture_sha256": hashlib.sha256(actual).hexdigest(),
            "recipe_sha256": recipe_sha256,
            "size": {"width": before.width, "height": before.height},
            "pixel_threshold": threshold, "tolerance_radius": tolerance_radius,
            "tolerance_method": "bidirectional-local-rgb-envelope-with-region-margin",
            "regions": entries,
            "perceptual_or_functional_accuracy": "not_measured"}
