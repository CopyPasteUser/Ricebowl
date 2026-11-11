"""Owner-private, content-addressed RicePlate icon and TrueType font assets.

No executable payloads, recipe-supplied paths, or system font installation.
Assets are read only by fixed SHA-256 identities and have immutable attribution.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import struct
from dataclasses import dataclass
from pathlib import Path

from . import assets, pack, recipes


ICON_ID = re.compile(r"icon-[0-9a-f]{64}\Z")
FONT_ID = re.compile(r"font-[0-9a-f]{64}\Z")
MAX_ICON_BYTES = 128 * 1024
MAX_FONT_BYTES = 1024 * 1024
ICON_DIMENSION = 48
ICON_ACTIONS = ("applications", "terminal", "lock")
SYSTEM_FONT_DIRS = tuple(map(Path, ("/usr/share/fonts", "/usr/local/share/fonts",
                                    "/usr/share/texmf/fonts")))


class StyleAssetError(ValueError):
    """A visual asset failed safety, provenance or integrity validation."""


@dataclass(frozen=True)
class StyleAsset:
    identifier: str
    kind: str
    label: str
    provenance: dict[str, str]


def _identity(data: bytes, kind: str) -> str:
    validate(data, kind)
    return kind + "-" + hashlib.sha256(data).hexdigest()


def validate(data: bytes, kind: str) -> None:
    """Reject malformed or oversized images/fonts *before* persisting bytes."""
    if kind == "icon":
        if len(data) > MAX_ICON_BYTES:
            raise StyleAssetError("Icon PNG exceeds 128 KiB")
        try:
            assets.validate_png(data)
        except assets.AssetError as exc:
            raise StyleAssetError(f"Invalid icon PNG: {exc}") from exc
        width, height, depth, color = struct.unpack_from(">IIBB", data, 16)
        if (width, height, depth, color) != (ICON_DIMENSION, ICON_DIMENSION, 8, 6):
            raise StyleAssetError("Icons must be exactly 48×48 RGBA PNGs")
    elif kind == "font":
        if len(data) < 12 or len(data) > MAX_FONT_BYTES or data[:4] != b"\x00\x01\x00\x00":
            raise StyleAssetError("Only bounded TrueType-outline .ttf fonts are supported")
        tables = struct.unpack_from(">H", data, 4)[0]
        if not 7 <= tables <= 64 or 12 + tables * 16 > len(data):
            raise StyleAssetError("Malformed TrueType table directory")
        seen: set[bytes] = set()
        spans = []
        for index in range(tables):
            tag, _checksum, offset, size = struct.unpack_from(">4sIII", data, 12 + index * 16)
            if (tag in seen or size == 0 or offset < 12 + tables * 16
                    or offset + size > len(data)):
                raise StyleAssetError("Unsafe TrueType table bounds or duplicates")
            seen.add(tag)
            spans.append((offset, offset + size))
        if not {b"cmap", b"head", b"hhea", b"hmtx", b"maxp", b"loca", b"glyf"} <= seen:
            raise StyleAssetError("TrueType font is missing required outline tables")
        spans.sort()
        if any(end > next_start for (_, end), (next_start, _) in zip(spans, spans[1:])):
            raise StyleAssetError("Overlapping TrueType tables")
    else:
        raise StyleAssetError("Unknown visual asset type")


def _collection(*, create: bool) -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    root = Path(configured) if configured else Path.home() / ".config"
    if not root.is_absolute():
        raise StyleAssetError("XDG_CONFIG_HOME must be absolute")
    directory = root / "ricebowl" / "visual-assets"
    for folder in (root, root / "ricebowl", directory):
        if create and not os.path.lexists(folder):
            folder.mkdir(mode=0o700)
        try:
            info = folder.lstat()
        except FileNotFoundError:
            if not create:
                return directory
            raise StyleAssetError("Cannot create private asset collection") from None
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o022 or (folder == directory and info.st_mode & 0o077)):
            raise StyleAssetError("Unsafe visual asset collection")
    return directory


def _kind(identifier: str) -> str:
    if type(identifier) is str and ICON_ID.fullmatch(identifier):
        return "icon"
    if type(identifier) is str and FONT_ID.fullmatch(identifier):
        return "font"
    raise StyleAssetError("Invalid visual asset ID")


def read(identifier: str) -> bytes:
    kind = _kind(identifier)
    suffix = ".png" if kind == "icon" else ".ttf"
    path = _collection(create=False) / (identifier + suffix)
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            info = os.fstat(stream.fileno())
            maximum = MAX_ICON_BYTES if kind == "icon" else MAX_FONT_BYTES
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077 or info.st_size > maximum):
                raise StyleAssetError("Unsafe private asset permissions or size")
            data = stream.read(maximum + 1)
    except OSError as exc:
        raise StyleAssetError("Visual asset could not be read safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if _identity(data, kind) != identifier:
        raise StyleAssetError("Visual asset content hash does not match")
    return data


def _record(identifier: str) -> StyleAsset:
    kind = _kind(identifier)
    path = _collection(create=False) / (identifier + ".json")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077 or info.st_size > 2048):
                raise StyleAssetError("Unsafe attribution record")
            data = json.loads(stream.read(2049).decode("utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise StyleAssetError("Invalid visual asset attribution") from exc
    if (type(data) is not dict or set(data) != {"id", "label", "provenance"}
            or data["id"] != identifier or type(data["label"]) is not str
            or not re.fullmatch(r"[A-Za-z0-9 ._+-]{1,60}", data["label"])):
        raise StyleAssetError("Invalid visual asset attribution fields")
    try:
        declared = pack._provenance(data["provenance"])
    except (pack.PackError, TypeError, AttributeError) as exc:
        raise StyleAssetError("Invalid visual asset provenance") from exc
    return StyleAsset(identifier, kind, data["label"], declared)


def entry(identifier: str) -> StyleAsset:
    read(identifier)
    return _record(identifier)


def list_assets(kind: str) -> list[StyleAsset]:
    if kind not in ("font", "icon"):
        raise StyleAssetError("Unknown visual asset type")
    folder = _collection(create=False)
    if not folder.exists():
        return []
    found = []
    for path in sorted(folder.iterdir()):
        if len(found) >= 64:
            break
        if path.suffix == (".ttf" if kind == "font" else ".png"):
            try:
                found.append(entry(path.stem))
            except (StyleAssetError, OSError):
                continue
    return found


def importable_font_source(path: Path) -> bool:
    """Allow owner files and public distro font trees, never unrelated private data."""
    if not path.is_absolute() or path.suffix != ".ttf":
        return False
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022
                or not 12 <= info.st_size <= MAX_FONT_BYTES):
            return False
        if info.st_uid == os.geteuid():
            return True
        # Package files can be mapped to e.g. nobody in an unprivileged
        # container. Require an unmodifiable public distribution path rather
        # than assuming numeric uid 0 on every supported filesystem.
        if not info.st_mode & 0o004:
            return False
        real = path.resolve(strict=True)
        for root in SYSTEM_FONT_DIRS:
            if real.is_relative_to(root):
                directory = real.parent
                while directory != root:
                    if directory.stat().st_mode & 0o022:
                        return False
                    directory = directory.parent
                return not root.stat().st_mode & 0o022
        return False
    except (OSError, ValueError):
        return False


def import_asset(source: Path, *, kind: str, label: str,
                 provenance: dict[str, str]) -> StyleAsset:
    if (type(label) is not str or re.fullmatch(r"[A-Za-z0-9 ._+-]{1,60}", label) is None
            or not source.is_absolute() or source.suffix != (".png" if kind == "icon" else ".ttf")):
        raise StyleAssetError("Choose a named absolute PNG icon or TTF font file")
    declared = pack._provenance(provenance)
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            maximum = MAX_ICON_BYTES if kind == "icon" else MAX_FONT_BYTES
            if (not stat.S_ISREG(info.st_mode)
                    or (info.st_uid != os.geteuid()
                        and not (kind == "font" and importable_font_source(source)))
                    or info.st_mode & 0o022 or info.st_size > maximum):
                raise StyleAssetError("Asset must be an owner-controlled regular file within limits")
            data = stream.read(maximum + 1)
    except OSError as exc:
        raise StyleAssetError("Cannot open visual asset safely") from exc
    identifier = _identity(data, kind)
    return _install_verified_asset(identifier, kind, data, label, declared)


def _install_verified_asset(identifier: str, kind: str, data: bytes, label: str,
                            provenance: dict[str, str]) -> StyleAsset:
    """Publish attribution before bytes so a process crash can be retried.

    A receipt-only record is not exposed by the asset catalog and can only
    be completed by the *same* immutable declaration. Pre-existing bytes
    without a receipt cannot be attributed retroactively to a new author.
    Neither file is replaced, including when another writer races us.
    """
    declared = _verify_existing_asset(identifier, kind, data, label, provenance)
    folder = _collection(create=True)
    image = folder / (identifier + (".png" if kind == "icon" else ".ttf"))
    record = folder / (identifier + ".json")
    if os.path.lexists(record):
        if _record(identifier) != declared:
            raise StyleAssetError("Asset already has different attribution")
    else:
        if os.path.lexists(image):
            raise StyleAssetError("Unattributed asset cannot be adopted")
        payload = (json.dumps({"id": identifier, "label": label,
                               "provenance": provenance},
                              sort_keys=True, ensure_ascii=False) + "\n").encode()
        recipes._write_private_new(record, payload)
    if os.path.lexists(image):
        if read(identifier) != data:
            raise StyleAssetError("Asset already exists with different bytes")
    else:
        recipes._write_private_new(image, data, suffix=image.suffix)
    return declared


def _verify_existing_asset(identifier: str, kind: str, data: bytes, label: str,
                           provenance: dict[str, str]) -> StyleAsset:
    """Read-only collision check; suitable before a multi-asset pack import."""
    folder = _collection(create=False)
    image = folder / (identifier + (".png" if kind == "icon" else ".ttf"))
    record = folder / (identifier + ".json")
    declared = StyleAsset(identifier, kind, label, provenance)
    if os.path.lexists(record):
        if _record(identifier) != declared:
            raise StyleAssetError("Asset already has different attribution")
    elif os.path.lexists(image):
        raise StyleAssetError("Unattributed asset cannot be adopted")
    if os.path.lexists(image) and read(identifier) != data:
        raise StyleAssetError("Asset already exists with different bytes")
    return declared


def preflight_pack_asset(identifier: str, data: bytes, *, label: str,
                         provenance: dict[str, str]) -> StyleAsset:
    """Reject predictable asset collisions without creating or changing files."""
    kind = _kind(identifier)
    if (_identity(data, kind) != identifier or type(label) is not str or
            re.fullmatch(r"[A-Za-z0-9 ._+-]{1,60}", label) is None):
        raise StyleAssetError("Invalid pack asset identity or label")
    declared = pack._provenance(provenance)
    return _verify_existing_asset(identifier, kind, data, label, declared)


def store_pack_asset(identifier: str, data: bytes, *, label: str,
                     provenance: dict[str, str]) -> StyleAsset:
    """Install a verified archive asset immutably; never change the current rice."""
    kind = _kind(identifier)
    validate(data, kind)
    if _identity(data, kind) != identifier:
        raise StyleAssetError("Pack asset hash does not match")
    declared = pack._provenance(provenance)
    return _install_verified_asset(identifier, kind, data, label, declared)
