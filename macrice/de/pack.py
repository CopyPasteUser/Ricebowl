"""Portable, non-executable RicePacks for the experimental Wayland shell.

Only validated recipe data and declared provenance are included. A RicePack
never contains scripts or active-session instructions. V3 may include a PNG
wallpaper; v4 may also include a bounded TrueType font and 48px RGBA icons.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tempfile
import zipfile
import fcntl
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import assets, recipes, review


PACK_VERSION = 4
PACK_FORMAT = "org.ricebowl.ricepack"
MAX_PACK_BYTES = 6 * 1024 * 1024
MAX_METADATA_BYTES = 4096
MAX_MANIFEST_BYTES = 16384
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
_ID = re.compile(r"[a-z][a-z0-9-]{1,31}\Z")
_LICENSES = frozenset(("unspecified", "CC0-1.0", "CC-BY-4.0", "MIT",
                       "OFL-1.1", "Apache-2.0", "custom"))
_ORIGINS = frozenset(("unspecified", "original", "ai-assisted", "adapted"))
_DEFAULT_PROVENANCE = {
    "author": "", "license": "unspecified", "origin": "unspecified", "source_reference": "",
}
_RECEIPT_SUFFIX = ".ricepack-provenance"
_IMPORT_LOCK = ".ricepack-import.lock"
_IMPORT_PENDING = ".ricepack-import-pending.ricepack"
_IMPORT_LOCK_TIMEOUT = 5.0


def _bundled_wallpaper(recipe: recipes.PanelRecipe) -> tuple[str, str]:
    """Pin the original installed wallpaper bytes without bundling executables."""
    asset_id = recipe.wallpaper or "aero-seven-blue"
    path = recipes.wallpaper_path(recipe)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 8 * 1024 * 1024:
                raise PackError("Bundled wallpaper is unavailable or unsafe",
                                code="asset_unavailable")
            data = stream.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024:
                raise PackError("Bundled wallpaper is oversized", code="asset_unavailable")
    except OSError as exc:
        raise PackError("Bundled wallpaper is unavailable", code="asset_unavailable") from exc
    return asset_id, _digest(data)


def _custom_wallpaper(recipe: recipes.PanelRecipe) -> bytes | None:
    if recipe.schema_version < 6 or not assets.ASSET_ID.fullmatch(recipe.wallpaper or ""):
        return None
    try:
        return assets.read(recipe.wallpaper)[1]
    except assets.AssetError as exc:
        raise PackError("Private wallpaper is missing or unsafe", code="asset_unavailable") from exc


def _wallpaper_identity(recipe: recipes.PanelRecipe) -> tuple[str, str]:
    if recipe.schema_version >= 6 and assets.ASSET_ID.fullmatch(recipe.wallpaper or ""):
        data = _custom_wallpaper(recipe)
        assert data is not None
        return recipe.wallpaper, _digest(data)
    return _bundled_wallpaper(recipe)


def _asset_receipt(recipe: recipes.PanelRecipe, provenance: dict[str, str]) -> dict[str, Any]:
    asset_id, sha = _wallpaper_identity(recipe)
    return {"version": 1, "wallpaper": {"id": asset_id, "sha256": sha,
                                        "provenance": provenance}}


def _visual_assets(recipe: recipes.PanelRecipe) -> tuple[list[tuple[str, bytes]], dict[str, Any]]:
    """Resolve only referenced private assets, never arbitrary paths from JSON."""
    from . import style_assets
    included: list[tuple[str, bytes]] = []
    receipts: dict[str, Any] = {"font": None, "icons": {}}
    if recipe.artwork is None:
        return included, receipts
    candidates = [("font", recipe.artwork.font, "assets/font.ttf")]
    candidates.extend(("icon", asset_id, f"assets/icons/{action}.png")
                      for action, asset_id in zip(style_assets.ICON_ACTIONS, recipe.artwork.icons))
    for kind, identifier, path in candidates:
        if identifier in ("builtin", "builtin-luna"):
            continue
        try:
            asset = style_assets.entry(identifier)
            data = style_assets.read(identifier)
        except style_assets.StyleAssetError as exc:
            raise PackError("Referenced font/icon asset is missing or unsafe",
                            code="asset_unavailable") from exc
        if asset.kind != kind:
            raise PackError("Visual asset kind does not match recipe", code="asset_mismatch")
        receipt = {"id": identifier, "sha256": _digest(data),
                   "label": asset.label, "provenance": asset.provenance}
        if kind == "font":
            receipts["font"] = receipt
        else:
            receipts["icons"][path.split("/")[-1].removesuffix(".png")] = receipt
        included.append((path, data))
    return included, receipts


def _provenance_receipt(manifest: dict[str, Any], recipe: recipes.PanelRecipe) -> bytes:
    """Bind imported license/origin attribution to the exact reviewed recipe."""
    wallpaper = (manifest["asset_manifest"]["wallpaper"]["provenance"]
                 if manifest["format_version"] >= 2 else dict(_DEFAULT_PROVENANCE))
    # The archive validator already pinned these bytes. Do not depend on a
    # *completed* private wallpaper install to calculate the receipt: import
    # preflight must inspect existing collisions before writing any asset.
    if manifest["format_version"] >= 2:
        wallpaper_id = manifest["asset_manifest"]["wallpaper"]["id"]
        wallpaper_sha = manifest["asset_manifest"]["wallpaper"]["sha256"]
    else:
        wallpaper_id, wallpaper_sha = _wallpaper_identity(recipe)
    return _json_bytes({"version": 1,
                        "semantic_sha256": manifest["recipe"]["semantic_sha256"],
                        "wallpaper_id": wallpaper_id, "wallpaper_sha256": wallpaper_sha,
                        "provenance": manifest["provenance"],
                        "wallpaper_provenance": wallpaper})


def _stored_provenance(recipe: recipes.PanelRecipe) -> tuple[dict[str, str], dict[str, str]] | None:
    """Read a private import receipt only for this exact installed recipe ID."""
    try:
        folder = recipes._private_recipe_dir(create=False)
    except recipes.RecipeError as exc:
        raise PackError("Unsafe private recipe collection", code="provenance_unavailable") from exc
    location = folder / f"{recipe.recipe_id}{_RECEIPT_SUFFIX}"
    if not os.path.lexists(location):
        return None
    saved = _parse_object(_read_owned_file(location, suffix=_RECEIPT_SUFFIX,
                                          limit=MAX_METADATA_BYTES, owner_private=True))
    if (set(saved) != {"version", "semantic_sha256", "wallpaper_id",
                      "wallpaper_sha256", "provenance", "wallpaper_provenance"}
            or type(saved["version"]) is not int or saved["version"] != 1
            or type(saved["semantic_sha256"]) is not str
            or type(saved["wallpaper_id"]) is not str
            or type(saved["wallpaper_sha256"]) is not str):
        raise PackError("Malformed imported provenance receipt", code="provenance_unavailable")
    canonical = review._manifest(recipe)
    if saved["semantic_sha256"] != review._semantic_hash(canonical):
        raise PackError("Imported rice changed since its license/provenance receipt",
                        code="provenance_stale")
    if (saved["wallpaper_id"], saved["wallpaper_sha256"]) != _wallpaper_identity(recipe):
        raise PackError("Bundled artwork changed since its license/provenance receipt",
                        code="provenance_stale")
    main = _provenance(saved["provenance"] if type(saved["provenance"]) is dict else {})
    wallpaper = _provenance(saved["wallpaper_provenance"]
                            if type(saved["wallpaper_provenance"]) is dict else {})
    return main, wallpaper


class PackError(ValueError):
    """Invalid or unsafe portable package; no active desktop was changed."""

    def __init__(self, message: str, *, code: str = "invalid_pack") -> None:
        super().__init__(message)
        self.code = code


def _json_bytes(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_object(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"),
                           object_pairs_hook=recipes._object_without_duplicates)
    except (ValueError, UnicodeError, RecursionError, TypeError) as exc:
        raise PackError("Malformed or duplicate-key RicePack JSON") from exc
    if type(value) is not dict:
        raise PackError("RicePack JSON must be an object")
    return value


def _provenance(value: dict[str, Any]) -> dict[str, str]:
    if set(value) != set(_DEFAULT_PROVENANCE):
        raise PackError("Unsupported RicePack provenance fields")
    if (type(value["author"]) is not str or len(value["author"]) > 80
            or type(value["source_reference"]) is not str
            or len(value["source_reference"]) > 256
            or type(value["license"]) is not str or value["license"] not in _LICENSES
            or type(value["origin"]) is not str or value["origin"] not in _ORIGINS):
        raise PackError("Invalid RicePack provenance")
    for field in ("author", "source_reference"):
        if any(ord(char) < 32 or ord(char) == 127 for char in value[field]):
            raise PackError("RicePack provenance contains control characters")
    return value


def _read_owned_file(path: Path, *, suffix: str, limit: int,
                     owner_private: bool = False) -> bytes:
    if not path.is_absolute() or path.suffix != suffix:
        raise PackError(f"Input must be an absolute {suffix} file", code="invalid_input")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as stream:
            meta = os.fstat(stream.fileno())
            if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid()
                    or meta.st_mode & 0o022 or meta.st_size > limit
                    or (owner_private and meta.st_mode & 0o077)):
                raise PackError("Input is unsafe, unowned or too large", code="invalid_input")
            payload = stream.read(limit + 1)
            if len(payload) > limit:
                raise PackError("Input exceeds its size limit", code="invalid_input")
            return payload
    except OSError as exc:
        raise PackError("Input is unavailable or unsafe", code="invalid_input") from exc


def _read_recipe(token: str) -> recipes.PanelRecipe:
    try:
        if token in recipes.BUILTINS:
            return recipes.load(token)
        if _ID.fullmatch(token):
            return recipes.load(token)
        return recipes.parse(recipes._read_import_source(Path(token)))
    except (recipes.RecipeError, OSError) as exc:
        raise PackError("Invalid or unsafe source recipe", code="invalid_recipe") from exc


def _new_archive(destination: Path, payload: bytes) -> None:
    if not destination.is_absolute() or destination.suffix != ".ricepack":
        raise PackError("Output must be an absolute .ricepack file", code="invalid_output")
    if len(payload) > MAX_PACK_BYTES:
        raise PackError("RicePack exceeds size limit", code="invalid_output")
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".ricebowl-pack-",
                                                dir=destination.parent)
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)  # Atomic no-overwrite, including symlinks.
    except OSError as exc:
        raise PackError("Cannot publish RicePack without overwriting a file",
                        code="output_unavailable") from exc
    finally:
        if temporary is not None:
            os.unlink(temporary)


def export_pack(recipe_token: str, destination: Path,
                *, metadata: Path | None = None,
                wallpaper_provenance: dict[str, str] | None = None,
                declared_provenance: dict[str, str] | None = None) -> dict[str, Any]:
    """Build reproducible bytes for a validated recipe; do not select/apply it."""
    if not destination.is_absolute() or destination.suffix != ".ricepack":
        raise PackError("Output must be an absolute .ricepack file", code="invalid_output")
    recipe = _read_recipe(recipe_token)
    declared_wallpaper = wallpaper_provenance
    provenance = dict(_DEFAULT_PROVENANCE)
    wallpaper_provenance = dict(_DEFAULT_PROVENANCE)
    if metadata is None and _ID.fullmatch(recipe_token) and recipe_token not in recipes.BUILTINS:
        remembered = _stored_provenance(recipe)
        if remembered is not None:
            provenance, wallpaper_provenance = remembered
    if metadata is not None:
        if declared_wallpaper is not None or declared_provenance is not None:
            raise PackError("Choose either a metadata file or declared provenance")
        declared = _parse_object(_read_owned_file(
            metadata, suffix=".json", limit=MAX_METADATA_BYTES))
        if "wallpaper_provenance" in declared:
            wallpaper = declared.pop("wallpaper_provenance")
            wallpaper_provenance = _provenance(wallpaper if type(wallpaper) is dict else {})
        provenance = _provenance(declared)
    if declared_provenance is not None:
        provenance = _provenance(declared_provenance)
    if declared_wallpaper is not None:
        wallpaper_provenance = _provenance(declared_wallpaper)
    canonical = review._manifest(recipe)
    recipe_payload = _json_bytes(canonical)
    # The canonical form must itself be the exact runtime schema, not a
    # Creator-only representation or an accidentally lossy normalization.
    try:
        if review._manifest(recipes.parse(recipe_payload)) != canonical:
            raise PackError("Recipe cannot be serialized losslessly", code="invalid_recipe")
    except recipes.RecipeError as exc:
        raise PackError("Canonical recipe is invalid", code="invalid_recipe") from exc
    included_wallpaper = _custom_wallpaper(recipe)
    visual_entries, visual_receipts = _visual_assets(recipe)
    pack_version = 4 if visual_entries else 3 if included_wallpaper is not None else 2
    manifest = {
        "format": PACK_FORMAT,
        "format_version": pack_version,
        "recipe": {"path": "recipe.json", "id": recipe.recipe_id,
                   "schema_version": recipe.schema_version,
                   "sha256": _digest(recipe_payload),
                   "semantic_sha256": review._semantic_hash(canonical)},
        "provenance": provenance,
        "runtime_assets": ("visual-assets-v1" if pack_version == 4 else
                           "one-private-content-addressed-png" if included_wallpaper is not None
                           else "bundled-wallpapers-only"),
        "asset_manifest": _asset_receipt(recipe, wallpaper_provenance),
    }
    if pack_version == 4:
        manifest["asset_manifest"]["version"] = 2
        manifest["asset_manifest"]["visual"] = visual_receipts
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_STORED,
                         allowZip64=False) as archive:
        entries = [("ricepack.json", _json_bytes(manifest)), ("recipe.json", recipe_payload)]
        if included_wallpaper is not None:
            entries.append(("assets/wallpaper.png", included_wallpaper))
        entries.extend(visual_entries)
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)
    _new_archive(destination, memory.getvalue())
    return {"pack_version": pack_version, "ok": True, "created": True,
            "imported": False, "applied": False, "recipe_id": recipe.recipe_id,
            "package_sha256": _digest(memory.getvalue()), "manifest": manifest}


def _validate_archive(source: Path | bytes) -> tuple[dict[str, Any], bytes, bytes | None, dict[str, bytes], bytes]:
    from . import style_assets
    payload = (source if isinstance(source, bytes) else
               _read_owned_file(source, suffix=".ricepack", limit=MAX_PACK_BYTES))
    if len(payload) > MAX_PACK_BYTES:
        raise PackError("RicePack exceeds safe archive size", code="invalid_input")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            allowed_icons = {f"assets/icons/{action}.png" for action in style_assets.ICON_ACTIONS}
            if (not 2 <= len(entries) <= 7 or len(names) != len(entries)
                    or not {"ricepack.json", "recipe.json"} <= names
                    or names - ({"ricepack.json", "recipe.json", "assets/wallpaper.png",
                                 "assets/font.ttf"} | allowed_icons)):
                raise PackError("RicePack contains unexpected or duplicate data entries")
            for entry in entries:
                mode = entry.external_attr >> 16
                if (entry.flag_bits & 1 or entry.compress_type != zipfile.ZIP_STORED
                        or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                        or entry.file_size > (
                            MAX_MANIFEST_BYTES if entry.filename == "ricepack.json" else
                            recipes.MAX_RECIPE_BYTES if entry.filename == "recipe.json" else
                            style_assets.MAX_FONT_BYTES if entry.filename == "assets/font.ttf" else
                            style_assets.MAX_ICON_BYTES if entry.filename in allowed_icons else
                            assets.MAX_IMAGE_BYTES)):
                    raise PackError("Unsafe, compressed or oversized RicePack entry")
            metadata = _parse_object(archive.read("ricepack.json"))
            recipe_payload = archive.read("recipe.json")
            wallpaper_payload = (archive.read("assets/wallpaper.png")
                                 if "assets/wallpaper.png" in names else None)
            visual_payloads = {name: archive.read(name) for name in names
                               if name == "assets/font.ttf" or name in allowed_icons}
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError, ValueError) as exc:
        if isinstance(exc, PackError):
            raise
        raise PackError("Corrupt or invalid RicePack archive") from exc
    version = metadata.get("format_version")
    expected = {"format", "format_version", "recipe", "provenance", "runtime_assets"}
    if version in (2, 3, 4):
        expected.add("asset_manifest")
    expected_assets = ("visual-assets-v1" if version == 4 else
                       "one-private-content-addressed-png" if version == 3
                       else "bundled-wallpapers-only")
    if (set(metadata) != expected
            or metadata["format"] != PACK_FORMAT
            or type(version) is not int
            or version not in (1, 2, 3, PACK_VERSION)
            or metadata["runtime_assets"] != expected_assets
            or (version != 4 and bool(visual_payloads))
            or (version == 3 and wallpaper_payload is None)
            or (version not in (3, 4) and wallpaper_payload is not None)):
        raise PackError("Unsupported RicePack format or version")
    info = metadata["recipe"]
    if (type(info) is not dict
            or set(info) != {"path", "id", "schema_version", "sha256", "semantic_sha256"}
            or info["path"] != "recipe.json"
            or type(info["id"]) is not str or not _ID.fullmatch(info["id"])
            or type(info["schema_version"]) is not int
            or type(info["sha256"]) is not str
            or type(info["semantic_sha256"]) is not str):
        raise PackError("Invalid RicePack recipe manifest")
    _provenance(metadata["provenance"] if type(metadata["provenance"]) is dict else {})
    try:
        recipe = recipes.parse(recipe_payload)
    except recipes.RecipeError as exc:
        raise PackError("RicePack includes an invalid recipe") from exc
    if (recipe.recipe_id != info["id"] or recipe.schema_version != info["schema_version"]
            or _digest(recipe_payload) != info["sha256"]
            or review._semantic_hash(review._manifest(recipe)) != info["semantic_sha256"]):
        raise PackError("RicePack recipe fingerprint or identity mismatch")
    if version in (2, 3, 4):
        asset_manifest = metadata["asset_manifest"]
        required = {"version", "wallpaper", "visual"} if version == 4 else {"version", "wallpaper"}
        if (type(asset_manifest) is not dict or set(asset_manifest) != required
                or type(asset_manifest["version"]) is not int
                or asset_manifest["version"] != (2 if version == 4 else 1)):
            raise PackError("Invalid RicePack asset manifest")
        wallpaper = asset_manifest["wallpaper"]
        if (type(wallpaper) is not dict
                or set(wallpaper) != {"id", "sha256", "provenance"}
                or type(wallpaper["id"]) is not str
                or type(wallpaper["sha256"]) is not str):
            raise PackError("Invalid bundled wallpaper receipt")
        _provenance(wallpaper["provenance"] if type(wallpaper["provenance"]) is dict else {})
        if wallpaper_payload is None:
            if (wallpaper["id"], wallpaper["sha256"]) != _bundled_wallpaper(recipe):
                raise PackError("Bundled wallpaper identity or checksum does not match",
                                code="asset_mismatch")
        else:
            if (recipe.schema_version < 6 or wallpaper["id"] != recipe.wallpaper
                    or not assets.ASSET_ID.fullmatch(wallpaper["id"])
                    or wallpaper_payload is None):
                raise PackError("Invalid content-addressed wallpaper identity",
                                code="asset_mismatch")
            try:
                expected_id = assets.image_id(wallpaper_payload)
            except assets.AssetError as exc:
                raise PackError("RicePack contains an invalid PNG", code="asset_mismatch") from exc
            if (expected_id != wallpaper["id"]
                    or _digest(wallpaper_payload) != wallpaper["sha256"]):
                raise PackError("RicePack wallpaper checksum does not match", code="asset_mismatch")
        if version == 4:
            artwork = recipe.artwork
            visual = asset_manifest["visual"]
            if (artwork is None or type(visual) is not dict
                    or set(visual) != {"font", "icons"} or type(visual["icons"]) is not dict):
                raise PackError("Visual asset receipt is missing or malformed")
            expected_records: dict[str, str] = {}
            if artwork.font != "builtin":
                expected_records["assets/font.ttf"] = artwork.font
            for action, asset_id in zip(style_assets.ICON_ACTIONS, artwork.icons):
                if asset_id not in ("builtin", "builtin-luna"):
                    expected_records[f"assets/icons/{action}.png"] = asset_id
            if (not expected_records or set(visual_payloads) != set(expected_records)
                    or set(visual["icons"]) != {
                        name.split("/")[-1].removesuffix(".png") for name in expected_records
                        if name.startswith("assets/icons/")}
                    or (visual["font"] is None) != (artwork.font == "builtin")):
                raise PackError("Visual asset archive entries do not match the recipe")
            declared_assets: dict[str, dict[str, Any]] = {}
            for filename, identifier in expected_records.items():
                record = (visual["font"] if filename == "assets/font.ttf" else
                          visual["icons"][filename.split("/")[-1].removesuffix(".png")])
                if (type(record) is not dict or set(record) != {"id", "sha256", "label", "provenance"}
                        or record["id"] != identifier
                        or type(record["sha256"]) is not str
                        or type(record["label"]) is not str
                        or re.fullmatch(r"[A-Za-z0-9 ._+-]{1,60}", record["label"]) is None):
                    raise PackError("Invalid font/icon asset attribution")
                _provenance(record["provenance"] if type(record["provenance"]) is dict else {})
                if identifier in declared_assets and declared_assets[identifier] != record:
                    raise PackError("One visual asset has conflicting provenance declarations",
                                    code="asset_mismatch")
                declared_assets[identifier] = record
                kind = "font" if filename == "assets/font.ttf" else "icon"
                try:
                    calculated = style_assets._identity(visual_payloads[filename], kind)
                except style_assets.StyleAssetError as exc:
                    raise PackError("Invalid font/icon asset data", code="asset_mismatch") from exc
                if calculated != identifier or _digest(visual_payloads[filename]) != record["sha256"]:
                    raise PackError("Font/icon checksum does not match", code="asset_mismatch")
    return metadata, recipe_payload, wallpaper_payload, visual_payloads, payload


def inspect_pack(source: Path) -> dict[str, Any]:
    """Verify all archive entries, fingerprints and the real recipe schema."""
    metadata, _, _, _, _ = _validate_archive(source)
    return {"pack_version": metadata["format_version"], "ok": True, "valid": True,
            "imported": False, "applied": False, "manifest": metadata}


def _preflight_import(metadata: dict[str, Any], payload: bytes,
                      wallpaper_bytes: bytes | None,
                      visual_payloads: dict[str, bytes]) -> bytes:
    """Inspect every known destination before publishing the first pack asset.

    Private immutable files remain the crash-retry boundary. This prevents a
    predictable later collision (including stale provenance and a bad existing
    wallpaper) from leaving earlier, otherwise valid font/icon files behind.
    It is not a cross-process or power-loss atomic transaction.
    """
    if metadata["recipe"]["id"] in recipes.BUILTINS:
        raise PackError("Cannot replace a reserved built-in recipe", code="reserved_id")
    try:
        folder = recipes._private_recipe_dir(create=False)
    except recipes.RecipeError as exc:
        raise PackError("Private recipe collection is unsafe", code="import_unavailable") from exc
    token = metadata["recipe"]["id"]
    if os.path.lexists(folder / f"{token}.json"):
        raise PackError("Cannot replace an installed recipe", code="import_unavailable")
    attribution = _provenance_receipt(metadata, recipes.parse(payload))
    receipt = folder / f"{token}{_RECEIPT_SUFFIX}"
    if os.path.lexists(receipt):
        try:
            prior = _read_owned_file(receipt, suffix=_RECEIPT_SUFFIX,
                                     limit=MAX_METADATA_BYTES, owner_private=True)
        except PackError as exc:
            raise PackError("Existing private provenance is unsafe",
                            code="import_unavailable") from exc
        if prior != attribution:
            raise PackError("Existing provenance does not match this pack",
                            code="import_unavailable")
    if wallpaper_bytes is not None:
        identifier = metadata["asset_manifest"]["wallpaper"]["id"]
        try:
            existing = assets._collection(create=False) / f"{identifier}.png"
            if os.path.lexists(existing) and assets.read(identifier)[1] != wallpaper_bytes:
                raise assets.AssetError("Installed wallpaper content differs")
        except assets.AssetError as exc:
            raise PackError("Private wallpaper conflicts with this pack",
                            code="asset_unavailable") from exc
    if visual_payloads:
        from . import style_assets
        visual = metadata["asset_manifest"]["visual"]
        for filename, data in sorted(visual_payloads.items()):
            record = (visual["font"] if filename == "assets/font.ttf" else
                      visual["icons"][filename.split("/")[-1].removesuffix(".png")])
            try:
                style_assets.preflight_pack_asset(record["id"], data,
                                                  label=record["label"],
                                                  provenance=record["provenance"])
            except style_assets.StyleAssetError as exc:
                raise PackError("Private font/icon asset conflicts with this pack",
                                code="asset_unavailable") from exc
    return attribution


def _sync_directory(folder: Path) -> None:
    """Make previously fsynced immutable file links durable before recipe commit."""
    descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _import_guard(folder: Path):
    """Serialize cooperating pack importers and retain a private stable lock inode."""
    location = folder / _IMPORT_LOCK
    descriptor = os.open(location, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise PackError("Unsafe private RicePack import lock", code="recovery_blocked")
        deadline = time.monotonic() + _IMPORT_LOCK_TIMEOUT
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise PackError("Another private RicePack import is still running",
                                    code="import_busy") from None
                time.sleep(0.05)
        yield
    finally:
        os.close(descriptor)


def _result(metadata: dict[str, Any], *, recovered: bool) -> dict[str, Any]:
    return {"pack_version": metadata["format_version"], "ok": True, "valid": True,
            "imported": True, "applied": False, "provenance_saved": True,
            "recovered": recovered, "recipe_id": metadata["recipe"]["id"],
            "semantic_sha256": metadata["recipe"]["semantic_sha256"]}


def _publish_import(metadata: dict[str, Any], payload: bytes,
                    wallpaper_bytes: bytes | None,
                    visual_payloads: dict[str, bytes], *, recovering: bool) -> None:
    """Publish assets first and the visible recipe last, with durable ordering."""
    folder = recipes._private_recipe_dir(create=True)
    token = metadata["recipe"]["id"]
    destination = folder / f"{token}.json"
    receipt = folder / f"{token}{_RECEIPT_SUFFIX}"
    attribution = _provenance_receipt(metadata, recipes.parse(payload))
    if os.path.lexists(destination):
        # After SIGKILL the recipe may already have been linked, but the
        # pending archive not removed. Only that exact completed import may
        # be treated as already installed, never a different recipe.
        if not recovering or (
            _read_owned_file(destination, suffix=".json", limit=recipes.MAX_RECIPE_BYTES,
                             owner_private=True) != payload or
            _read_owned_file(receipt, suffix=_RECEIPT_SUFFIX,
                             limit=MAX_METADATA_BYTES, owner_private=True) != attribution
        ):
            raise PackError("Installed recipe differs from the pending import",
                            code="recovery_blocked")
    else:
        _preflight_import(metadata, payload, wallpaper_bytes, visual_payloads)

    if wallpaper_bytes is not None:
        stored_id, _ = assets.store(wallpaper_bytes)
        if stored_id != metadata["asset_manifest"]["wallpaper"]["id"]:
            raise PackError("Wallpaper changed while importing", code="asset_mismatch")
        _sync_directory(assets._collection(create=False))
    if visual_payloads:
        from . import style_assets
        visual = metadata["asset_manifest"]["visual"]
        for filename, data in sorted(visual_payloads.items()):
            record = (visual["font"] if filename == "assets/font.ttf" else
                      visual["icons"][filename.split("/")[-1].removesuffix(".png")])
            style_assets.store_pack_asset(record["id"], data,
                                          label=record["label"],
                                          provenance=record["provenance"])
        _sync_directory(style_assets._collection(create=False))
    if os.path.lexists(receipt):
        if (_read_owned_file(receipt, suffix=_RECEIPT_SUFFIX,
                             limit=MAX_METADATA_BYTES, owner_private=True) != attribution):
            raise PackError("Existing provenance does not match this pack",
                            code="import_unavailable")
    else:
        recipes._write_private_new(receipt, attribution, suffix=_RECEIPT_SUFFIX)
    _sync_directory(folder)
    if not os.path.lexists(destination):
        recipes._write_private_new(destination, payload)
    _sync_directory(folder)


def _recover_locked(folder: Path) -> tuple[dict[str, Any], bytes] | None:
    """Replay the previously validated immutable archive; never delete assets."""
    pending = folder / _IMPORT_PENDING
    if not os.path.lexists(pending):
        return None
    source = _read_owned_file(pending, suffix=".ricepack", limit=MAX_PACK_BYTES,
                              owner_private=True)
    metadata, payload, wallpaper, visual, _ = _validate_archive(source)
    _publish_import(metadata, payload, wallpaper, visual, recovering=True)
    os.unlink(pending)
    _sync_directory(folder)
    return metadata, source


def recover_pack_import() -> dict[str, Any]:
    """Explicit, owner-local crash recovery; no desktop or selection changes."""
    try:
        folder = recipes._private_recipe_dir(create=False)
        if not folder.exists():
            return {"ok": True, "pending": False, "recovered": False,
                    "imported": False, "applied": False}
        with _import_guard(folder):
            outcome = _recover_locked(folder)
        if outcome is None:
            return {"ok": True, "pending": False, "recovered": False,
                    "imported": False, "applied": False}
        return {**_result(outcome[0], recovered=True), "pending": False}
    except (OSError, recipes.RecipeError, assets.AssetError, ValueError) as exc:
        if isinstance(exc, PackError):
            raise
        raise PackError("Pending RicePack recovery could not complete safely",
                        code="recovery_blocked") from exc


def import_pack(source: Path, *, expected_manifest: dict[str, Any] | None = None
                ) -> dict[str, Any]:
    """Durably stage a validated RicePack, then commit the recipe last.

    A failed import retains one private pinned archive for lock-serialized
    roll-forward after process exit or I/O errors. Its intermediate assets are
    inert until the complete recipe is published; shared assets are not deleted.
    """
    metadata, payload, wallpaper, visual, archive = _validate_archive(source)
    if expected_manifest is not None and metadata != expected_manifest:
        raise PackError("RicePack changed since review; inspect it again",
                        code="pack_changed")
    try:
        if not os.path.lexists(recipes._private_recipe_dir(create=False) / _IMPORT_PENDING):
            _preflight_import(metadata, payload, wallpaper, visual)
        folder = recipes._private_recipe_dir(create=True)
        with _import_guard(folder):
            recovered = _recover_locked(folder)
            if recovered is not None and recovered[1] == archive:
                return _result(recovered[0], recovered=True)
            _preflight_import(metadata, payload, wallpaper, visual)
            pending = folder / _IMPORT_PENDING
            recipes._write_private_new(pending, archive, suffix=".ricepack")
            _sync_directory(folder)  # Journal is durable BEFORE the first asset write.
            _publish_import(metadata, payload, wallpaper, visual, recovering=False)
            os.unlink(pending)
            _sync_directory(folder)
    except (OSError, recipes.RecipeError, assets.AssetError, ValueError) as exc:
        if isinstance(exc, PackError):
            raise
        raise PackError("RicePack import interrupted; use de pack-recover to resume",
                        code="import_unavailable") from exc
    return _result(metadata, recovered=False)


def invalid_pack(error: PackError) -> dict[str, Any]:
    """Stable path-free errors for agents; no privacy-sensitive file paths."""
    return {"pack_version": PACK_VERSION, "ok": False, "imported": False,
            "applied": False, "error": {"code": error.code, "message": str(error)}}
