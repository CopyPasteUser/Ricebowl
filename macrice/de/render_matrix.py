"""Reviewable four-geometry captures from actual isolated RicePlate renders.

The archive is a bounded data-only receipt. It never activates a rice, starts
an agent, copies the user's screen or claims perceptual/functional parity.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
import tempfile
import zlib
import zipfile
from pathlib import Path

from .render import RenderError, render

MATRIX_VERSION = 1
MATRIX_CASES = (
    ("compact", 1024, 768, 1.0),
    ("laptop", 1366, 768, 1.0),
    ("desktop", 1920, 1080, 1.0),
    ("fractional", 1366, 768, 1.25),
)
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_CAPTURE_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class MatrixError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__({
            "invalid_matrix_request": "Choose a new absolute .zip path and a valid recipe",
            "invalid_matrix_archive": "The matrix archive is invalid or inconsistent",
            "matrix_failed": "One or more isolated Wayland captures failed",
        }[code])


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stream_digest(stream) -> str:
    digest = hashlib.sha256()
    stream.seek(0)
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _png_geometry(data: bytes) -> tuple[int, int]:
    if not 57 <= len(data) <= MAX_CAPTURE_BYTES or data[:8] != PNG_SIGNATURE:
        raise MatrixError("invalid_matrix_archive")
    offset = 8
    geometry = None
    seen_image_data = False
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + length
        if end > len(data):
            break
        kind = data[offset + 4:offset + 8]
        if (not all(65 <= char <= 90 or 97 <= char <= 122 for char in kind)
                or zlib.crc32(data[offset + 4:end - 4]) !=
                struct.unpack_from(">I", data, end - 4)[0]):
            break
        if geometry is None:
            if kind != b"IHDR" or length != 13:
                break
            geometry = struct.unpack_from(">II", data, offset + 8)
        elif kind == b"IHDR":
            break
        if kind == b"IDAT":
            seen_image_data = True
        if kind == b"IEND":
            if length == 0 and seen_image_data and end == len(data):
                return geometry
            break
        offset = end
    raise MatrixError("invalid_matrix_archive")


def _zip_entry(name: str, data: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100600 << 16
    return info, data


def _validate_manifest(manifest: object) -> dict:
    if (not isinstance(manifest, dict) or set(manifest) != {
            "matrix_version", "source", "recipe", "cases", "mutates_active_desktop",
            "interactive_session", "functional_or_perceptual_accuracy"}
            or manifest.get("matrix_version") != MATRIX_VERSION):
        raise MatrixError("invalid_matrix_archive")
    recipe = manifest.get("recipe")
    if (not isinstance(recipe, dict)
            or set(recipe) != {"id", "schema_version", "semantic_sha256"}
            or not isinstance(recipe.get("id"), str)
            or not recipe["id"] or type(recipe.get("schema_version")) is not int
            or not isinstance(recipe.get("semantic_sha256"), str)
            or len(recipe["semantic_sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in recipe["semantic_sha256"])):
        raise MatrixError("invalid_matrix_archive")
    if (manifest.get("source") != "isolated-headless-labwc-native-riceplate"
            or manifest.get("mutates_active_desktop") is not False
            or manifest.get("interactive_session") is not False
            or manifest.get("functional_or_perceptual_accuracy") != "not_measured"):
        raise MatrixError("invalid_matrix_archive")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != len(MATRIX_CASES):
        raise MatrixError("invalid_matrix_archive")
    for item, (case_id, width, height, scale) in zip(cases, MATRIX_CASES):
        if (not isinstance(item, dict)
                or set(item) != {"id", "entry", "geometry", "bytes", "sha256"}
                or item.get("id") != case_id
                or item.get("entry") != f"captures/{case_id}.png"
                or item.get("geometry") != {"width": width, "height": height, "scale": scale}
                or type(item.get("bytes")) is not int
                or not 57 <= item["bytes"] <= MAX_CAPTURE_BYTES
                or not isinstance(item.get("sha256"), str)
                or len(item["sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in item["sha256"])):
            raise MatrixError("invalid_matrix_archive")
    return manifest


def _unique_json(pairs: list[tuple[str, object]]) -> dict:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise MatrixError("invalid_matrix_archive")
        obj[key] = value
    return obj


def inspect_matrix(source: Path) -> dict:
    """Check every archive entry without extraction or external processes."""
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= MAX_ARCHIVE_BYTES):
                raise MatrixError("invalid_matrix_archive")
            with zipfile.ZipFile(stream, "r") as archive:
                entries = archive.infolist()
                expected = {"manifest.json", *(f"captures/{case[0]}.png" for case in MATRIX_CASES)}
                if len(entries) != len(expected) or {item.filename for item in entries} != expected:
                    raise MatrixError("invalid_matrix_archive")
                for entry in entries:
                    if (entry.flag_bits & 1 or entry.compress_type != zipfile.ZIP_STORED
                            or stat.S_IFMT(entry.external_attr >> 16) != stat.S_IFREG
                            or entry.file_size > (MAX_MANIFEST_BYTES if entry.filename == "manifest.json"
                                                   else MAX_CAPTURE_BYTES)):
                        raise MatrixError("invalid_matrix_archive")
                manifest_bytes = archive.read("manifest.json")
                manifest = _validate_manifest(json.loads(manifest_bytes, object_pairs_hook=_unique_json))
                for item in manifest["cases"]:
                    data = archive.read(item["entry"])
                    width, height = _png_geometry(data)
                    if (len(data) != item["bytes"] or _digest(data) != item["sha256"]
                            or (width, height) != (item["geometry"]["width"],
                                                    item["geometry"]["height"])):
                        raise MatrixError("invalid_matrix_archive")
            receipt = {**manifest, "archive": str(source),
                       "archive_sha256": _stream_digest(stream), "verified": True}
        return receipt
    except (OSError, ValueError, KeyError, TypeError, struct.error, zipfile.BadZipFile,
            RuntimeError, zlib.error) as exc:
        raise MatrixError("invalid_matrix_archive") from exc


def render_matrix(recipe_token: str | None, output: Path | None) -> dict:
    """Publish one complete, no-overwrite archive only after four real renders."""
    if (not recipe_token or output is None or not output.is_absolute()
            or output.suffix.lower() != ".zip" or not output.parent.is_dir()
            or os.path.lexists(output)):
        raise MatrixError("invalid_matrix_request")
    try:
        with tempfile.TemporaryDirectory(prefix=".ricebowl-matrix-", dir=output.parent) as folder:
            temp = Path(folder)
            cases = []
            entries = []
            recipe_receipt = None
            for case_id, width, height, scale in MATRIX_CASES:
                path = temp / f"{case_id}.png"
                result = render(recipe_token, path, width=width, height=height, scale=scale)
                current_recipe = result["recipe"]
                if recipe_receipt is None:
                    recipe_receipt = current_recipe
                elif recipe_receipt != current_recipe:
                    raise MatrixError("matrix_failed")
                data = path.read_bytes()
                try:
                    image_geometry = _png_geometry(data)
                except MatrixError as exc:
                    raise MatrixError("matrix_failed") from exc
                if (image_geometry != (width, height)
                        or len(data) != result["output"]["bytes"]
                        or _digest(data) != result["output"]["sha256"]):
                    raise MatrixError("matrix_failed")
                entries.append(_zip_entry(f"captures/{case_id}.png", data))
                cases.append({"id": case_id, "entry": f"captures/{case_id}.png",
                              "geometry": {"width": width, "height": height, "scale": scale},
                              "sha256": _digest(data), "bytes": len(data)})
            manifest = {"matrix_version": MATRIX_VERSION, "source":
                        "isolated-headless-labwc-native-riceplate", "recipe": recipe_receipt,
                        "cases": cases, "mutates_active_desktop": False,
                        "interactive_session": False,
                        "functional_or_perceptual_accuracy": "not_measured"}
            manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
            if len(manifest_bytes) > MAX_MANIFEST_BYTES:
                raise MatrixError("matrix_failed")
            archive_path = temp / "matrix.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(*_zip_entry("manifest.json", manifest_bytes))
                for entry in entries:
                    archive.writestr(*entry)
            os.chmod(archive_path, 0o600)
            verified = inspect_matrix(archive_path)
            try:
                os.link(archive_path, output, follow_symlinks=False)
            except FileExistsError as exc:
                raise MatrixError("invalid_matrix_request") from exc
        return {**verified, "archive": str(output)}
    except RenderError:
        raise
    except MatrixError:
        raise
    except (OSError, KeyError, TypeError, ValueError, zipfile.BadZipFile) as exc:
        raise MatrixError("matrix_failed") from exc
