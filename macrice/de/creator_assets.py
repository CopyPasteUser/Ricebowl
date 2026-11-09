"""Owner-private Rice Creator wallpaper catalog and user-declared provenance.

The runtime and RicePack v3 already support content-addressed PNG wallpapers.
This module adds *metadata*, not a second asset store, decoder or active apply.
Metadata is immutable and bound to the content hash; it never automatically
records a source filesystem path, executable content or a verified license.
"""

from __future__ import annotations

import json
import os
import stat
import struct
from dataclasses import dataclass
from pathlib import Path

from . import assets, pack, recipes

MAX_LISTED_WALLPAPERS = 64
MAX_METADATA_BYTES = 2048
UNKNOWN_PROVENANCE = {
    "author": "", "license": "unspecified", "origin": "unspecified", "source_reference": "",
}


@dataclass(frozen=True)
class WallpaperEntry:
    asset_id: str
    label: str
    width: int
    height: int
    size: int
    provenance: dict[str, str]


def _label(value: str) -> str:
    if type(value) is not str:
        raise assets.AssetError("Image name must be text")
    cleaned = value.strip()
    if (not 1 <= len(cleaned) <= 60 or any(ord(char) < 32 or ord(char) == 127
                                           for char in cleaned)
            or "/" in cleaned or "\\" in cleaned):
        raise assets.AssetError("Choose a 1–60 character image name without paths or controls")
    return cleaned


def _meta_path(asset_id: str) -> Path:
    if not assets.ASSET_ID.fullmatch(asset_id):
        raise assets.AssetError("Invalid wallpaper asset ID")
    return assets._collection(create=False) / (asset_id + ".json")


def _metadata(asset_id: str) -> tuple[str, dict[str, str]]:
    location = _meta_path(asset_id)
    try:
        fd = os.open(location, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077 or info.st_size > MAX_METADATA_BYTES):
                raise assets.AssetError("Unsafe wallpaper provenance record")
            content = stream.read(MAX_METADATA_BYTES + 1)
    except FileNotFoundError:
        return "Imported PNG · " + asset_id[6:18], dict(UNKNOWN_PROVENANCE)
    except OSError as exc:
        raise assets.AssetError("Cannot read private wallpaper provenance") from exc
    try:
        document = json.loads(content.decode("utf-8"),
                              object_pairs_hook=recipes._object_without_duplicates)
        if (type(document) is not dict or set(document) != {"version", "asset_id", "label", "provenance"}
                or type(document["version"]) is not int or document["version"] != 1
                or document["asset_id"] != asset_id):
            raise ValueError("Invalid provenance record identity")
        return _label(document["label"]), pack._provenance(document["provenance"])
    except (ValueError, UnicodeError, TypeError, KeyError, RecursionError) as exc:
        raise assets.AssetError("Malformed or mismatched wallpaper provenance") from exc


def entry(asset_id: str) -> WallpaperEntry:
    """Read and verify both the immutable image and any private declaration."""
    _path, data = assets.read(asset_id)
    label, provenance = _metadata(asset_id)
    width, height = struct.unpack_from(">II", data, 16)
    return WallpaperEntry(asset_id, label, width, height, len(data), provenance)


def catalog() -> list[WallpaperEntry]:
    """List up to 64 valid assets. Ignore damaged files without following links."""
    directory = assets._collection(create=False)
    if not directory.exists():
        return []
    found: list[WallpaperEntry] = []
    for location in sorted(directory.iterdir()):
        if location.suffix != ".png" or not assets.ASSET_ID.fullmatch(location.stem):
            continue
        try:
            found.append(entry(location.stem))
        except (assets.AssetError, OSError):
            continue  # A damaged or raced asset must not prevent editing others.
        if len(found) >= MAX_LISTED_WALLPAPERS:
            break
    return found


def import_wallpaper(source: Path, *, label: str,
                     provenance: dict[str, str]) -> WallpaperEntry:
    """Import a local, owner-controlled PNG and pin the user's declaration once."""
    label = _label(label)
    try:
        declaration = pack._provenance(dict(provenance))
    except (pack.PackError, TypeError, ValueError) as exc:
        raise assets.AssetError("Invalid author, license, origin or source reference") from exc
    # The ID is fixed-width: bound the declaration before installing a PNG.
    # A rejected declaration must not leave an orphan image in the collection.
    template = {"version": 1, "asset_id": "asset-" + "0" * 64,
                "label": label, "provenance": declaration}
    if len((json.dumps(template, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")) > MAX_METADATA_BYTES:
        raise assets.AssetError("Wallpaper attribution is too large")
    asset_id, _path = assets.import_png(source)
    metadata = _meta_path(asset_id)
    if os.path.lexists(metadata):
        existing_label, existing_provenance = _metadata(asset_id)
        if (existing_label, existing_provenance) != (label, declaration):
            raise assets.AssetError("Image is already imported with different attribution")
    else:
        payload = (json.dumps({"version": 1, "asset_id": asset_id, "label": label,
                               "provenance": declaration}, sort_keys=True, ensure_ascii=False)
                   + "\n").encode("utf-8")
        try:
            recipes._write_private_new(metadata, payload)
        except (OSError, recipes.RecipeError) as exc:
            raise assets.AssetError("Could not save private attribution without overwriting") from exc
    return entry(asset_id)
