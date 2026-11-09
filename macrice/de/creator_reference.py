"""Private screenshot references for the on-demand Rice Creator 0.6 studio.

References belong to a Creator draft identity, *not* to a live rice or a
RicePack. All comparisons use the existing offline visual QA engine and real
render bytes; screenshots never become executable recipe input.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import creator_workspace, recipes, visual_qa

MAX_PNG_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 16_777_216
_CREATOR_ID = re.compile(r"creator-[0-9a-f]{12}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class ReferenceError(ValueError):
    """A reference image, private record or comparison is unavailable."""


@dataclass(frozen=True)
class ReferenceInfo:
    recipe_id: str
    name: str
    sha256: str
    width: int
    height: int


def _folder() -> Path:
    try:
        base = creator_workspace._private_directory()
        target = base.parent / "references"
        if not os.path.lexists(target):
            target.mkdir(mode=0o700)
        info = target.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077):
            raise ReferenceError("Reference storage must be an owner-private directory")
        return target
    except (creator_workspace.WorkspaceError, OSError) as exc:
        raise ReferenceError("Private Creator reference storage is unavailable") from exc


def _id(recipe_id: str) -> str:
    if type(recipe_id) is not str or not _CREATOR_ID.fullmatch(recipe_id):
        raise ReferenceError("References require a private Creator draft identity")
    return recipe_id


def _read_private(path: Path, *, limit: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077 or info.st_size > limit):
                raise ReferenceError("Reference storage has unsafe permissions or size")
            return stream.read(limit + 1)
    except OSError as exc:
        raise ReferenceError("Reference file cannot be read safely") from exc


def _image_size(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise ReferenceError("Install python3-pil to compare screenshots") from exc
    if len(data) > MAX_PNG_BYTES:
        raise ReferenceError("Reference PNG exceeds 64 MiB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if (image.format != "PNG" or not 1 <= width <= 8192
                    or not 1 <= height <= 8192 or width * height > MAX_PIXELS):
                raise ReferenceError("Reference must be a bounded PNG screenshot")
            image.load()  # Validate the entire compressed raster, not just the header.
            return width, height
    except (OSError, ValueError, UnidentifiedImageError, SyntaxError) as exc:
        if isinstance(exc, ReferenceError):
            raise
        raise ReferenceError("Reference PNG is damaged or unsupported") from exc


def _source_bytes(source: Path) -> bytes:
    if not source.is_absolute() or source.suffix.lower() != ".png":
        raise ReferenceError("Choose an absolute local PNG screenshot")
    try:
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o022 or info.st_size > MAX_PNG_BYTES):
                raise ReferenceError("Screenshot must be an owner-controlled PNG within 64 MiB")
            return stream.read(MAX_PNG_BYTES + 1)
    except OSError as exc:
        raise ReferenceError("Cannot safely open the selected PNG") from exc


def select(recipe_id: str, source: Path) -> ReferenceInfo:
    """Copy one verified PNG by digest, then atomically select it for a draft."""
    _id(recipe_id)
    data = _source_bytes(source)
    width, height = _image_size(data)
    digest = hashlib.sha256(data).hexdigest()
    folder = _folder()
    image = folder / f"reference-{digest}.png"
    if os.path.lexists(image):
        if _read_private(image, limit=MAX_PNG_BYTES) != data:
            raise ReferenceError("Stored reference image differs from its SHA-256 identity")
    else:
        recipes._write_private_new(image, data, suffix=".png")
    name = "".join(char if 32 <= ord(char) < 127 else "_" for char in source.name[:100])
    record = {"version": 1, "recipe_id": recipe_id, "name": name,
              "sha256": digest, "width": width, "height": height}
    payload = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
    pointer = folder / f"{recipe_id}.json"
    # The temp and final pointer are in the same owner-only directory.
    descriptor, temporary = tempfile.mkstemp(prefix=".reference-", suffix=".json", dir=folder)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
        os.replace(temporary, pointer)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)
    return ReferenceInfo(recipe_id, name, digest, width, height)


def selected(recipe_id: str) -> ReferenceInfo | None:
    """Verify the owner-private selection and image digest on every access."""
    pointer = _folder() / f"{_id(recipe_id)}.json"
    if not os.path.lexists(pointer):
        return None
    try:
        data = json.loads(_read_private(pointer, limit=1024),
                          object_pairs_hook=recipes._object_without_duplicates)
        if (type(data) is not dict
                or set(data) != {"version", "recipe_id", "name", "sha256", "width", "height"}
                or type(data["version"]) is not int or data["version"] != 1
                or data["recipe_id"] != recipe_id
                or type(data["name"]) is not str or not 1 <= len(data["name"]) <= 100
                or type(data["sha256"]) is not str or not _SHA.fullmatch(data["sha256"])
                or type(data["width"]) is not int or type(data["height"]) is not int):
            raise ReferenceError("Malformed reference selection record")
        image = _read_private(_folder() / f"reference-{data['sha256']}.png",
                              limit=MAX_PNG_BYTES)
        if (hashlib.sha256(image).hexdigest() != data["sha256"]
                or _image_size(image) != (data["width"], data["height"])):
            raise ReferenceError("Reference screenshot failed integrity verification")
        return ReferenceInfo(recipe_id, data["name"], data["sha256"],
                             data["width"], data["height"])
    except ReferenceError:
        raise
    except (ValueError, UnicodeError, TypeError, KeyError, RecursionError) as exc:
        raise ReferenceError("Malformed reference selection record") from exc


def clear(recipe_id: str) -> None:
    """Unlink only this draft's selection; immutable screenshots stay recoverable."""
    (_folder() / f"{_id(recipe_id)}.json").unlink(missing_ok=True)


def image_bytes(recipe_id: str) -> bytes:
    """Read the currently selected, fully verified reference for on-demand preview."""
    info = selected(recipe_id)
    if info is None:
        raise ReferenceError("Select a reference before opening its preview")
    return _read_private(_folder() / f"reference-{info.sha256}.png", limit=MAX_PNG_BYTES)


def compare_capture(recipe_id: str, actual: bytes, *, recipe_token: str | None = None,
                    threshold: int = 24, tolerance_radius: int = 1) -> tuple[dict, dict[str, bytes]]:
    """Compute source/real/50% overlay/wipe/heatmap without persistent outputs."""
    info = selected(recipe_id)
    if info is None:
        raise ReferenceError("Select a reference image before comparing")
    if len(actual) > MAX_PNG_BYTES or _image_size(actual) != (info.width, info.height):
        raise ReferenceError("Native capture and reference resolutions differ; choose matching output size")
    source = _folder() / f"reference-{info.sha256}.png"
    try:
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix="ricebowl-creator-compare-") as temp:
            root = Path(temp)
            captured = root / "actual.png"
            recipes._write_private_new(captured, actual, suffix=".png")
            overlay, heatmap = root / "overlay.png", root / "heatmap.png"
            report = visual_qa.compare(source, captured, threshold=threshold,
                                       tolerance_radius=tolerance_radius, recipe_token=recipe_token,
                                       overlay=overlay, tolerant_heatmap=heatmap)
            with Image.open(source) as before, Image.open(captured) as after:
                left, right = before.convert("RGB"), after.convert("RGB")
                middle = info.width // 2
                wipe = Image.new("RGB", left.size)
                wipe.paste(left.crop((0, 0, middle, info.height)), (0, 0))
                wipe.paste(right.crop((middle, 0, info.width, info.height)), (middle, 0))
                stream = io.BytesIO()
                wipe.save(stream, format="PNG")
            return report, {"native": actual,
                            "reference": _read_private(source, limit=MAX_PNG_BYTES),
                            "overlay": overlay.read_bytes(), "wipe": stream.getvalue(),
                            "heatmap": heatmap.read_bytes()}
    except (OSError, ValueError) as exc:
        raise ReferenceError(f"Visual comparison failed: {exc}") from exc
