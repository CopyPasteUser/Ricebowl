"""Rice Creator 0.9: reference-pixel pointer geometry and bounded QA history.

This is deliberately a read-only comparison journal. Neither annotations nor
measurements are instructions to change a live desktop or a saved recipe.
"""

from __future__ import annotations

import math
from typing import Any

from . import creator_regions

VERSION = 1
MAX_MEASUREMENTS = 12


def drag_rectangle(start: tuple[float, float], end: tuple[float, float], *,
                   displayed: tuple[int, int], source: tuple[int, int],
                   kind: str) -> dict[str, Any]:
    """Convert a drag over a fitted screenshot to exact *source-pixel* bounds.

    Points are relative to the displayed image, not the scroll viewport. The
    press must start on the image; release is clamped so an outside release
    still produces a bounded rectangle. Left/top round down, right/bottom up.
    """
    if (kind not in creator_regions.KINDS or len(start) != 2 or len(end) != 2 or
            len(displayed) != 2 or len(source) != 2 or
            any(type(v) not in (int, float) or not math.isfinite(v)
                for v in (*start, *end)) or
            any(type(v) is not int or v <= 0 for v in (*displayed, *source))):
        raise creator_regions.RegionError("Invalid pointer or screenshot geometry")
    dw, dh = displayed
    sw, sh = source
    if not (0 <= start[0] <= dw and 0 <= start[1] <= dh):
        raise creator_regions.RegionError("Start the selection inside the screenshot")
    # A click or an accidental tremor is not an intentional region selection.
    if abs(end[0] - start[0]) < 3 or abs(end[1] - start[1]) < 3:
        raise creator_regions.RegionError("Drag at least 3 displayed pixels in both directions")
    bounds = []
    for a, b, display_len, source_len in zip(
            start, end, displayed, source):
        low = max(0.0, min(float(display_len), min(a, b)))
        high = max(0.0, min(float(display_len), max(a, b)))
        lower = math.floor(low * source_len / display_len)
        upper = math.ceil(high * source_len / display_len)
        if upper <= lower:
            raise creator_regions.RegionError("Region collapses outside the screenshot")
        bounds.append((lower, upper))
    rect = {"kind": kind, "x": bounds[0][0], "y": bounds[1][0],
            "width": bounds[0][1] - bounds[0][0],
            "height": bounds[1][1] - bounds[1][0]}
    return creator_regions.validate([rect], size=source)[0]


def _identity(report: dict) -> tuple:
    try:
        if report["region_report_version"] != creator_regions.VERSION:
            raise ValueError("Unsupported measurement version")
        size = report["size"]
        rects = tuple((item["kind"], *(item["rect"][field] for field in
                                              ("x", "y", "width", "height")))
                      for item in report["regions"])
        regions = [{"kind": kind, "x": x, "y": y, "width": w, "height": h}
                   for kind, x, y, w, h in rects]
        creator_regions.validate(regions, size=(size["width"], size["height"]))
        if not regions or len({item["number"] for item in report["regions"]}) != len(regions):
            raise ValueError("Empty or repeated region numbering")
        if any(item["number"] != index for index, item in
               enumerate(report["regions"], start=1)):
            raise ValueError("Regions must retain their order")
        if (type(report["pixel_threshold"]) is not int or
                not 0 <= report["pixel_threshold"] <= 255 or
                type(report["tolerance_radius"]) is not int or
                report["tolerance_radius"] not in (0, 1, 2)):
            raise ValueError("Invalid pixel comparison policy")
        if any(type(report[key]) is not str or len(report[key]) != 64 or
               any(char not in "0123456789abcdef" for char in report[key])
               for key in ("reference_sha256", "capture_sha256", "recipe_sha256")):
            raise ValueError("Invalid measurement identity")
        for item in report["regions"]:
            for ratio in (item["changed_pixel_ratio"],
                          item["tolerance"]["changed_pixel_ratio"]):
                if type(ratio) not in (float, int) or not math.isfinite(ratio) or not 0 <= ratio <= 1:
                    raise ValueError("Invalid pixel error ratio")
        return (report["reference_sha256"], size["width"], size["height"],
                report["pixel_threshold"], report["tolerance_radius"], rects)
    except (KeyError, ValueError, TypeError, IndexError, creator_regions.RegionError) as exc:
        raise creator_regions.RegionError(f"Invalid measurement receipt: {exc}") from exc


def journal(reports: list[dict]) -> dict[str, Any]:
    """Compare repeated real captures with the *same* regions and pixel policy.

    Lower error is not automatically higher fidelity: only measured pixel error
    deltas are presented, with hashes for independently verifying provenance.
    """
    if type(reports) is not list or not 1 <= len(reports) <= MAX_MEASUREMENTS:
        raise creator_regions.RegionError("QA history must contain 1–12 measurements")
    identity = _identity(reports[0])
    for current in reports[1:]:
        if _identity(current) != identity:
            raise creator_regions.RegionError("Reference, regions or pixel policy changed")
    comparisons = []
    for previous, current in zip(reports, reports[1:]):
        changes = []
        for earlier, later in zip(previous["regions"], current["regions"]):
            delta = (later["tolerance"]["changed_pixel_ratio"] -
                     earlier["tolerance"]["changed_pixel_ratio"]) * 100
            changes.append({"number": later["number"], "kind": later["kind"],
                            "tolerated_changed_percentage_point_delta": round(delta, 5),
                            "direction": "lower" if delta < -1e-9 else
                                         "higher" if delta > 1e-9 else "unchanged"})
        comparisons.append({"from_recipe_sha256": previous["recipe_sha256"],
                            "to_recipe_sha256": current["recipe_sha256"],
                            "from_capture_sha256": previous["capture_sha256"],
                            "to_capture_sha256": current["capture_sha256"],
                            "regions": changes})
    return {"iteration_version": VERSION, "measurements": reports.copy(),
            "comparisons": comparisons,
            "interpretation": "Measured RGB pixel errors only; not perceptual or functional accuracy"}
