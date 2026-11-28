#!/usr/bin/env python3
"""Import real, green-CI X11 screenshots into the current WebP gallery.

Usage:
    /usr/bin/python3 scripts/import_ci_screenshots.py \
      /tmp/ricebowl-captures.zip --run-id 123456 --source-commit 40hexsha

The archive must come from the matching RiceBowl GitHub Actions run. All
required images are validated *before* any tracked asset is replaced. This
script never paints simulated notifications, windows, wallpaper or icons.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile
from zipfile import ZipFile

from PIL import Image, ImageChops, UnidentifiedImageError


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "screenshots/current"
PROFILES = ("aero", "windows10", "winxp", "winclassic", "chromeos", "frutiger")
VERSIONS = {f"{profile}-{view}": f"ricebowl-{profile}-{view}-0.9.1.png"
            for profile in PROFILES for view in ("start", "controls", "workspace")}
DEEP_VIEWS = (
    "programs", "detail", "classic", "tray-audio", "tray-network",
    "tray-battery", "tray-bluetooth", "tray-clock",
)
VERSIONS.update({f"winxp-{view}": f"ricebowl-winxp-{view}-0.9.1.png"
                 for view in DEEP_VIEWS})
VERSIONS.update({f"winxp-{view}": f"ricebowl-winxp-{view}-0.9.1-extra.png"
                 for view in ("properties", "notification-icons", "run", "help", "system")})
VERSIONS.update({f"chromeos-{view}": f"ricebowl-chromeos-{view}-0.9.1-extra.png"
                 for view in ("notifications", "settings")})
VERSIONS.update({f"windows10-settings-{view}":
                 f"ricebowl-windows10-settings-{view}-0.9.1-extra.png"
                 for view in ("home", "sound", "storage", "apps")})
VERSIONS.update({f"windows10-{view}": f"ricebowl-windows10-{view}-0.9.1-extra.png"
                 for view in ("letters", "actions-expanded", "audio", "calendar",
                              "network", "task-view")})
VERSIONS["macmenu-dark"] = "ricebowl-macmenu-dark-current.png"


def import_gallery(archive: Path, destination: Path, *, run_id: int,
                   source_commit: str, only: tuple[str, ...] | None = None,
                   origin: str | None = None) -> dict:
    """Import a capture archive.

    ``only`` selects a subset of gallery stems for a partial *recapture*: just
    those images (and their manifest entries) are replaced, every other image and
    the original CI provenance stay untouched. ``origin`` then describes the
    local capture environment instead of a hosted CI run.
    """
    if only is not None:
        unknown = sorted(set(only) - set(VERSIONS))
        if unknown:
            raise ValueError(f"Unknown gallery images: {', '.join(unknown)}")
    if only is None and run_id <= 0 or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("Provide an exact GitHub Actions run ID and 40-digit commit SHA")
    archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    fingerprints: set[str] = set()
    manifest_images = []

    # The ZIP is untrusted input. Never extract arbitrary paths from it and
    # limit each image before decoding. Work in a sibling temporary directory
    # so a damaged artifact cannot partially update the tracked gallery.
    destination.mkdir(parents=True, exist_ok=True)
    with ExitStack() as resources:
        temp = Path(resources.enter_context(
            tempfile.TemporaryDirectory(prefix="ricebowl-screenshot-", dir=destination.parent)))
        zipped = resources.enter_context(ZipFile(archive))
        for stem, source_name in VERSIONS.items():
            if only is not None and stem not in only:
                continue
            try:
                member = zipped.getinfo(source_name)
            except KeyError as exc:
                raise ValueError(f"Missing required screenshot: {source_name}") from exc
            minimum = 10_000 if stem == "macmenu-dark" else 12_000
            if not minimum < member.file_size < 12_000_000:
                raise ValueError(f"Unexpected capture size: {source_name}")
            raw = zipped.read(member)
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"Not a PNG screenshot: {source_name}")
            try:
                with Image.open(BytesIO(raw)) as source:
                    width, height = source.size
                    valid_resolution = ((320 <= width <= 1000 and 300 <= height <= 900)
                                        if stem == "macmenu-dark" else
                                        (width, height) == (1600, 900))
                    if source.format != "PNG" or not valid_resolution:
                        raise ValueError(f"Unexpected resolution: {source_name}")
                    pixels = source.convert("RGB")
            except (UnidentifiedImageError, OSError) as exc:
                raise ValueError(f"Corrupt capture: {source_name}") from exc
            signature = hashlib.sha256(pixels.tobytes()).hexdigest()
            if signature in fingerprints:
                raise ValueError(f"Duplicate image contents: {source_name}")
            fingerprints.add(signature)

            target = temp / f"{stem}.webp"
            pixels.save(target, format="WEBP", quality=86, method=6)
            with Image.open(target) as checked:
                if checked.size != pixels.size or checked.format != "WEBP":
                    raise ValueError(f"Bad WebP conversion: {stem}")
            manifest_images.append({
                "file": target.name,
                "capture": source_name,
                "pixels": [pixels.width, pixels.height],
                "png_sha256": hashlib.sha256(raw).hexdigest(),
                "webp_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            })

        # A historically clipped control panel could still be a valid PNG.
        # Check content in the actual expected region, not just dimensions.
        for profile in PROFILES:
            if only is not None and not (
                    f"{profile}-start" in only and f"{profile}-controls" in only):
                continue
            with (Image.open(temp / f"{profile}-start.webp") as start,
                  Image.open(temp / f"{profile}-controls.webp") as controls):
                region = ((460, 170, 1140, 750) if profile in
                          ("aero", "winxp", "winclassic") else
                          (1215, 385, 1594, 840))
                difference = ImageChops.difference(
                    start.convert("RGB").crop(region),
                    controls.convert("RGB").crop(region))
                changed = sum(1 for color in difference.getdata() if max(color) > 18)
                if changed < 20_000:
                    raise ValueError(f"Control panel appears invisible: {profile}")

        if only is not None:
            previous = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            for item in manifest_images:
                item["source_commit"] = source_commit
            replaced = {item["file"]: item for item in manifest_images}
            merged = [replaced.pop(item["file"], item) for item in previous["images"]]
            if replaced:
                raise ValueError("Partial recapture would add images: " + ", ".join(replaced))
            metadata = dict(previous)
            metadata["images"] = merged
            metadata.setdefault("recaptures", []).append({
                "capture_origin": origin or "local RiceBowl capture, native GTK3/XFWM4 virtual X11",
                "source_commit": source_commit,
                "source_archive_sha256": archive_digest,
                "imported_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "files": sorted(item["file"] for item in manifest_images),
            })
            (temp / "manifest.json").write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            for item in manifest_images:
                os.replace(temp / item["file"], destination / item["file"])
            os.replace(temp / "manifest.json", destination / "manifest.json")
            return metadata

        metadata = {
            "format": 1,
            "capture_origin": "RiceBowl GitHub Actions, native GTK3/XFWM4 virtual X11",
            "run_id": run_id,
            "source_commit": source_commit,
            "source_archive_sha256": archive_digest,
            "imported_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "desktop_resolution": [1600, 900],
            "images": manifest_images,
        }
        (temp / "manifest.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for item in manifest_images:
            os.replace(temp / item["file"], destination / item["file"])
        os.replace(temp / "manifest.json", destination / "manifest.json")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Downloaded green-CI artifact ZIP")
    parser.add_argument("--run-id", type=int, default=0,
                        help="GitHub Actions run ID (not used with --only)")
    parser.add_argument("--only", nargs="+", metavar="STEM",
                        help="partial recapture: replace only these gallery images")
    parser.add_argument("--origin", help="capture environment note for --only")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--destination", type=Path, default=DESTINATION)
    args = parser.parse_args()
    metadata = import_gallery(args.archive, args.destination,
                              run_id=args.run_id, source_commit=args.source_commit,
                              only=tuple(args.only) if args.only else None,
                              origin=args.origin)
    print(f"Imported {len(metadata['images'])} authentic X11 screenshots "
          f"from run {metadata['run_id']}")


if __name__ == "__main__":
    main()
