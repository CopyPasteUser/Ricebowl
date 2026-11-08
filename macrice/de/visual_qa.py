"""Offline, bounded PNG comparison shared by Runtime tools and the Creator CLI.

Visual metrics do not measure function, perception or interaction fidelity.
Pillow is an optional dependency loaded only when explicitly comparing images.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path

from . import recipes, review


def _metrics(diff, *, threshold: int) -> dict:
    """Measure an RGB difference image; scores never imply UI functionality."""
    width, height = diff.size
    histogram = diff.histogram()
    error_sum = sum((index % 256) * count for index, count in enumerate(histogram))
    pixels = (diff.get_flattened_data() if hasattr(diff, "get_flattened_data")
              else diff.getdata())
    changed = sum(1 for rgb in pixels if max(rgb) > threshold)
    return {
        "mean_absolute_rgb_error": round(error_sum / (width * height * 3), 4),
        "changed_pixels": changed,
        "changed_pixel_ratio": round(changed / (width * height), 6),
        "identical": error_sum == 0,
    }


def _recipe_regions(diff, recipe_token: str, threshold: int) -> dict:
    """Inspect real pixels occupied by the declared shell; never infer fidelity."""
    try:
        recipe = recipes.load(recipe_token)
    except recipes.RecipeError as exc:
        raise ValueError("Invalid or unsafe recipe") from exc
    width, height = diff.size
    panel_y = 0 if recipe.position == "top" else height - recipe.height
    regions = [
        ("panel", (0, panel_y, width, panel_y + recipe.height)),
        ("desktop", (0, recipe.height if recipe.position == "top" else 0,
                     width, height if recipe.position == "top" else panel_y)),
    ]
    if recipe.height >= height:
        raise ValueError("Capture too small for recipe panel")
    issues = []
    for number, icon in enumerate(recipe.desktop_icons or (), start=1):
        box = (icon.x, icon.y, icon.x + recipes.ICON_WIDTH,
               icon.y + recipes.ICON_HEIGHT)
        regions.append((f"desktop-icon-{number}", box))
    results = []
    for name, box in regions:
        x1, y1, x2, y2 = box
        clipped = (max(0, x1), max(0, y1), min(width, x2), min(height, y2))
        visible_width = max(0, clipped[2] - clipped[0])
        visible_height = max(0, clipped[3] - clipped[1])
        fraction = round((visible_width * visible_height) /
                         ((x2 - x1) * (y2 - y1)), 6)
        region = {"id": name, "expected_rect": {"x": x1, "y": y1,
                   "width": x2 - x1, "height": y2 - y1},
                  "visible_fraction": fraction}
        if visible_width and visible_height:
            region.update(_metrics(diff.crop(clipped), threshold=threshold))
        else:
            region["status"] = "outside_capture"
        if name.startswith("desktop-icon-"):
            if fraction < 1:
                issues.append({"region": name, "code": "icon_outside_output"})
            if (visible_width and visible_height and
                    clipped[1] < panel_y + recipe.height and clipped[3] > panel_y):
                issues.append({"region": name, "code": "icon_overlaps_panel"})
        results.append(region)
    manifest = review._manifest(recipe)
    return {"recipe": {"id": recipe.recipe_id,
                       "schema_version": recipe.schema_version,
                       "semantic_sha256": review._semantic_hash(manifest)},
            "regions": results, "layout_issues": issues}


def _save_private_png(image, path: Path) -> None:
    """Write once (0600), refusing existing files or symlinks."""
    if not path.is_absolute() or path.suffix.lower() != ".png":
        raise ValueError("Diagnostic output must be a new absolute .png path")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise ValueError("Diagnostic output exists or cannot be created") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            image.save(stream, format="PNG")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _tolerant_difference(before, after, radius: int):
    """Two-way local RGB envelope: tolerate small rasterization shifts, not missing shapes.

    Both directions matter: matching only the actual pixels to the reference
    would silently accept a missing thin line or glyph.
    """
    from PIL import Image, ImageChops, ImageFilter

    if radius == 0:
        return ImageChops.difference(before, after)

    def distance(source, target):
        result = []
        for channel, tested in zip(source.split(), target.split()):
            low = channel.filter(ImageFilter.MinFilter(2 * radius + 1))
            high = channel.filter(ImageFilter.MaxFilter(2 * radius + 1))
            result.append(ImageChops.lighter(ImageChops.subtract(low, tested),
                                            ImageChops.subtract(tested, high)))
        return Image.merge("RGB", result)

    return ImageChops.lighter(distance(before, after), distance(after, before))


def _private_json(path: Path) -> dict:
    if not path.is_absolute() or path.suffix.lower() != ".json":
        raise ValueError("Baseline must be an absolute private .json file")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size > 4096
                    or info.st_uid != os.getuid() or info.st_mode & 0o077):
                raise ValueError("Baseline must be an owner-private small regular file")
            data = json.loads(stream.read())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Baseline cannot be safely read") from exc
    if not isinstance(data, dict):
        raise ValueError("Baseline must be a JSON object")
    return data


def _validated_baseline(path: Path) -> dict:
    data = _private_json(path)
    recipe = data.get("recipe")
    geometry = data.get("size")
    policy = data.get("policy")
    if (set(data) != {"baseline_version", "reference_sha256", "recipe", "size", "policy"}
            or type(data["baseline_version"]) is not int or data["baseline_version"] != 1
            or not isinstance(recipe, dict)
            or set(recipe) != {"id", "schema_version", "semantic_sha256"}
            or not isinstance(recipe["id"], str) or not recipe["id"]
            or type(recipe["schema_version"]) is not int
            or not isinstance(geometry, dict) or set(geometry) != {"width", "height"}
            or not isinstance(policy, dict)
            or set(policy) != {"pixel_threshold", "tolerance_radius", "max_changed_ratio",
                               "require_no_layout_issues"}):
        raise ValueError("Unsupported or malformed visual baseline")
    if (any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (data["reference_sha256"], recipe["semantic_sha256"]))
            or type(geometry["width"]) is not int or type(geometry["height"]) is not int
            or geometry["width"] < 1 or geometry["height"] < 1
            or type(policy["pixel_threshold"]) is not int
            or not 0 <= policy["pixel_threshold"] <= 255
            or type(policy["tolerance_radius"]) is not int
            or policy["tolerance_radius"] not in (0, 1, 2)
            or type(policy["max_changed_ratio"]) not in (int, float)
            or not math.isfinite(policy["max_changed_ratio"])
            or not 0 <= policy["max_changed_ratio"] <= 1
            or policy["require_no_layout_issues"] is not True):
        raise ValueError("Visual baseline policy is invalid")
    return data


def _image_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_baseline(reference: Path, recipe_token: str, output: Path, *,
                    threshold: int = 24, tolerance_radius: int = 1,
                    max_changed_ratio: float = 0.01) -> dict:
    """Explicitly pin a reviewed PNG and recipe; never edit the source or select a rice."""
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise ValueError("Optional Pillow package is required for image comparison") from exc

    if (type(threshold) is not int or not 0 <= threshold <= 255
            or type(tolerance_radius) is not int or tolerance_radius not in (0, 1, 2)
            or type(max_changed_ratio) not in (int, float)
            or not math.isfinite(max_changed_ratio)
            or not 0 <= max_changed_ratio <= 1):
        raise ValueError("Invalid baseline tolerances")
    if (not output.is_absolute() or output.suffix.lower() != ".json"
            or not output.parent.is_dir()):
        raise ValueError("Baseline output must be a new absolute .json file")
    try:
        recipe = recipes.load(recipe_token)
        if reference.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("Reference exceeds image size limit")
        with Image.open(reference) as image:
            if (image.format != "PNG" or not 1 <= image.width <= 8192
                    or not 1 <= image.height <= 8192
                    or image.width * image.height > 16_777_216):
                raise ValueError("Reference must be a bounded PNG")
            image.verify()
            size = {"width": image.width, "height": image.height}
    except (OSError, UnidentifiedImageError, recipes.RecipeError) as exc:
        raise ValueError("Reference or recipe is invalid or unavailable") from exc
    try:
        digest = _image_digest(reference)
    except OSError as exc:
        raise ValueError("Reference became unavailable") from exc
    data = {
        "baseline_version": 1,
        "reference_sha256": digest,
        "recipe": {"id": recipe.recipe_id, "schema_version": recipe.schema_version,
                   "semantic_sha256": review._semantic_hash(review._manifest(recipe))},
        "size": size,
        "policy": {"pixel_threshold": threshold, "tolerance_radius": tolerance_radius,
                   "max_changed_ratio": max_changed_ratio, "require_no_layout_issues": True},
    }
    try:
        fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise ValueError("Baseline output exists or cannot be created") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, sort_keys=True, indent=2)
            stream.write("\n")
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return data


def compare(reference: Path, actual: Path, *, threshold: int = 24,
            recipe_token: str | None = None, overlay: Path | None = None,
            heatmap: Path | None = None, tolerance_radius: int = 0,
            tolerant_heatmap: Path | None = None, baseline: Path | None = None) -> dict:
    """Compare captures without modifying them; optional diagnostics are new files."""
    try:
        from PIL import Image, ImageChops, UnidentifiedImageError
    except ImportError as exc:
        raise ValueError("Optional Pillow package is required for image comparison") from exc

    approved = _validated_baseline(baseline) if baseline is not None else None
    if approved:
        if not recipe_token:
            raise ValueError("A baseline comparison requires the matching recipe")
        threshold = approved["policy"]["pixel_threshold"]
        tolerance_radius = approved["policy"]["tolerance_radius"]
    if type(threshold) is not int or not 0 <= threshold <= 255:
        raise ValueError("Threshold must be between 0 and 255")
    if type(tolerance_radius) is not int or tolerance_radius not in (0, 1, 2):
        raise ValueError("Tolerance radius must be 0, 1 or 2 pixels")
    outputs = [path for path in (overlay, heatmap, tolerant_heatmap) if path is not None]
    if (len({str(path.resolve()) for path in outputs}) != len(outputs)
            or any(not path.is_absolute() or path.suffix.lower() != ".png"
                   for path in outputs)):
        raise ValueError("Diagnostic outputs must be distinct absolute .png paths")
    try:
        if any(path.stat().st_size > 64 * 1024 * 1024 for path in (reference, actual)):
            raise ValueError("Capture exceeds the 64 MiB offline comparison limit")
    except OSError as exc:
        raise ValueError("Capture file is unavailable") from exc
    try:
        with Image.open(reference) as original, Image.open(actual) as captured:
            if original.format != "PNG" or captured.format != "PNG":
                raise ValueError("Only unmodified PNG captures are supported")
            if original.size != captured.size:
                raise ValueError("Capture dimensions differ")
            if not 1 <= original.width <= 8192 or not 1 <= original.height <= 8192:
                raise ValueError("Capture dimensions are outside the safe range")
            if original.width * original.height > 16_777_216:
                raise ValueError("Capture exceeds the safe 16-megapixel comparison limit")
            if approved and ({"width": original.width, "height": original.height} != approved["size"]
                             or _image_digest(reference) != approved["reference_sha256"]):
                raise ValueError("Approved baseline no longer matches reference or recipe")
            before, after = original.convert("RGB"), captured.convert("RGB")
            diff = ImageChops.difference(before, after)
            tolerant_diff = (_tolerant_difference(before, after, tolerance_radius)
                             if tolerance_radius else diff)
            result = {
                "comparison_version": 3 if (tolerance_radius or approved) else
                                      (2 if recipe_token else 1),
                "size": {"width": original.width, "height": original.height},
                "pixel_threshold": threshold,
                **_metrics(diff, threshold=threshold),
                "perceptual_or_functional_accuracy": "not_measured",
            }
            if recipe_token:
                result.update(_recipe_regions(diff, recipe_token, threshold))
            if tolerance_radius:
                result["tolerance"] = {
                    "radius_pixels": tolerance_radius,
                    "method": "bidirectional-local-rgb-envelope",
                    **_metrics(tolerant_diff, threshold=threshold),
                }
            if approved:
                if result["recipe"] != approved["recipe"]:
                    raise ValueError("Approved baseline no longer matches reference or recipe")
                changed = (result["tolerance"]["changed_pixel_ratio"] if tolerance_radius
                           else result["changed_pixel_ratio"])
                changed_pixels = (result["tolerance"]["changed_pixels"] if tolerance_radius
                                  else result["changed_pixels"])
                result["baseline"] = {
                    "version": 1,
                    "passed": changed_pixels <= (original.width * original.height *
                                                   approved["policy"]["max_changed_ratio"])
                              and not result["layout_issues"],
                    "changed_pixel_ratio": changed,
                    "max_changed_ratio": approved["policy"]["max_changed_ratio"],
                    "layout_issues": len(result["layout_issues"]),
                    "reference_sha256": approved["reference_sha256"],
                }
            written: list[Path] = []
            try:
                if overlay is not None:
                    _save_private_png(Image.blend(before, after, 0.5), overlay)
                    written.append(overlay)
                if heatmap is not None:
                    red, green, blue = diff.split()
                    intensity = ImageChops.lighter(ImageChops.lighter(red, green), blue)
                    intensity = intensity.point(lambda value: min(value * 4, 255))
                    empty = Image.new("L", diff.size, 0)
                    _save_private_png(Image.merge("RGB", (intensity, empty, empty)), heatmap)
                    written.append(heatmap)
                if tolerant_heatmap is not None:
                    red, green, blue = tolerant_diff.split()
                    intensity = ImageChops.lighter(ImageChops.lighter(red, green), blue)
                    intensity = intensity.point(lambda value: min(value * 4, 255))
                    empty = Image.new("L", diff.size, 0)
                    _save_private_png(Image.merge("RGB", (intensity, empty, empty)),
                                      tolerant_heatmap)
                    written.append(tolerant_heatmap)
            except Exception:
                for path in written:
                    path.unlink(missing_ok=True)
                raise
            if overlay is not None:
                result["overlay"] = str(overlay)
            if heatmap is not None:
                result["heatmap"] = str(heatmap)
            if tolerant_heatmap is not None:
                result["tolerant_heatmap"] = str(tolerant_heatmap)
            return result
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("Capture could not be decoded as a readable PNG") from exc
