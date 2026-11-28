"""Safe, version-aware migration of user-local RiceBowl theme and icon bundles.

Trust only byte-identical historical git objects shipped in this repository.
Unknown customizations are never overwritten without an explicit repair action.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path


class AssetConflict(ValueError):
    pass


def git_blob_sha(content: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()


@lru_cache(maxsize=1)
def trusted_assets() -> dict[str, frozenset[str]]:
    root = Path(__file__).resolve().parents[1] / "assets"
    trusted: dict[str, set[str]] = {}
    for name in ("trusted-ricehub-assets.json", "trusted-ricebowl-luna-091.json",
                 "trusted-ricebowl-aero-before-redesign.json",
                 "trusted-ricebowl-aero-seven-icons.json",
                 "trusted-ricebowl-frutiger-before-aqua.json",
                 "trusted-ricebowl-frutiger-aqua-091.json",
                 "trusted-ricebowl-classic-before-fidelity.json",
                 "trusted-ricebowl-ten-before-fidelity.json",
                 "trusted-ricebowl-chrome-before-fidelity.json",
                 "trusted-ricebowl-sg4-original-art.json"):
        raw = json.loads((root / name).read_text(encoding="utf-8"))
        if raw.get("schema") != 1 or not isinstance(raw.get("files"), dict):
            raise AssetConflict("Unsupported trusted asset manifest")
        for path, hashes in raw["files"].items():
            if not isinstance(path, str) or not isinstance(hashes, list) or any(
                    not isinstance(h, str) or len(h) != 40 or
                    any(ch not in "0123456789abcdef" for ch in h) for h in hashes):
                raise AssetConflict("Invalid trusted asset hash")
            trusted.setdefault(path, set()).update(hashes)
    return {name: frozenset(hashes) for name, hashes in trusted.items()}


def _relative_source_key(source: Path, relative: Path) -> str:
    # Bundle: <root>/assets/{themes|icons}/<RiceHub-name>/...
    if source.parent.name not in ("themes", "icons") or source.parent.parent.name != "assets":
        raise AssetConflict(f"Unsupported source asset bundle: {source}")
    return (Path("assets") / source.parent.name / source.name / relative).as_posix()


def _validate_source(source: Path) -> None:
    """Reject crafted, symlinked or incomplete source asset trees.

    A repair operation must enforce the same source checks as a normal
    theme installation, even though it deliberately bypasses destination
    content hashes.
    """
    if source.is_symlink() or not source.is_dir():
        raise AssetConflict(f"Missing or symlinked RiceBowl source assets: {source}")
    files = 0
    for entry in source.rglob("*"):
        if entry.is_symlink():
            raise AssetConflict(f"Refusing symlinked RiceBowl source asset: {entry}")
        if entry.is_file():
            files += 1
            if entry.stat().st_size > 2 * 1024 * 1024:
                raise AssetConflict(f"Unexpectedly large RiceBowl source asset: {entry}")
        elif not entry.is_dir():
            raise AssetConflict(f"Unsupported RiceBowl source entry: {entry}")
    if not files:
        raise AssetConflict(f"Empty RiceBowl source asset bundle: {source}")


def _validate_destination(target: Path) -> None:
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise AssetConflict(f"Refusing a symlink in RiceBowl asset destination: {target}")
    if target.exists():
        if not target.is_dir() or target.stat().st_uid != os.getuid():
            raise AssetConflict(f"Unmanaged RiceBowl asset destination: {target}")
        for entry in target.rglob("*"):
            if entry.is_symlink():
                raise AssetConflict(f"Refusing symlinked RiceBowl asset path: {entry}")
            if entry.stat().st_uid != os.getuid():
                raise AssetConflict(f"Unmanaged RiceBowl asset path: {entry}")


def inspect_bundle(source: Path, target: Path) -> None:
    """Verify a prior bundle without writing."""
    _validate_source(source)
    _validate_destination(target)
    if not target.exists():
        return
    source_files = {p.relative_to(source): p for p in source.rglob("*") if p.is_file()}
    current_files = {p.relative_to(target): p for p in target.rglob("*") if p.is_file()}
    if not current_files or not set(current_files).issubset(source_files):
        raise AssetConflict(
            f"Existing customized theme conflicts with RiceBowl: {target}. "
            "Use explicit 'macrice rice repair-assets STYLE' for a backed-up repair."
        )
    trusted = trusted_assets()
    for relative, current in current_files.items():
        local = current.read_bytes()
        expected = source_files[relative].read_bytes()
        if local == expected:
            continue
        # Exact branding-only upgrade is also supported in isolated test bundles.
        if ((relative.name == "index.theme" or relative.suffix == ".svg") and
                b"RiceBowl" in expected and
                local == expected.replace(b"RiceBowl", b"RiceHub")):
            continue
        try:
            key = _relative_source_key(source, relative)
        except AssetConflict:
            key = ""
        if git_blob_sha(local) not in trusted.get(key, frozenset()):
            raise AssetConflict(
                f"Existing customized theme conflicts with RiceBowl: {target} "
                f"(changed: {relative}). "
                "Use explicit 'macrice rice repair-assets STYLE' for a backed-up repair."
            )


def _stage(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".ricebowl-stage-", dir=target.parent))
    try:
        for entry in source.rglob("*"):
            relative = entry.relative_to(source)
            dest = stage / relative
            if entry.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(entry, dest, follow_symlinks=False)
                os.chmod(dest, 0o644)
    except BaseException:
        shutil.rmtree(stage)
        raise
    return stage


def install_bundle(source: Path, target: Path, *, repair: bool = False) -> Path | None:
    """Atomically replace a verified old bundle; retain its full recovery copy.

    Repair bypasses the historical hash comparison ONLY by explicit user action.
    It still refuses symlinked, unmanaged or non-user-owned targets.
    """
    _validate_source(source)
    _validate_destination(target)
    if not repair:
        inspect_bundle(source, target)
    if target.exists():
        new = {p.relative_to(source): p for p in source.rglob("*") if p.is_file()}
        old = {p.relative_to(target): p for p in target.rglob("*") if p.is_file()}
        if set(new) == set(old) and all(old[r].read_bytes() == p.read_bytes() for r, p in new.items()):
            return None
    stage = _stage(source, target)
    try:
        if not target.exists():
            if target.is_symlink():
                raise AssetConflict(f"Target changed to a symlink during install: {target}")
            os.replace(stage, target)
            return None
        _validate_destination(target)
        if not repair:
            inspect_bundle(source, target)
        archive = target.parent / ".ricebowl-asset-backups"
        if archive.is_symlink() or (archive.exists() and
                (not archive.is_dir() or archive.stat().st_uid != os.getuid())):
            raise AssetConflict(f"Unmanaged RiceBowl backup directory: {archive}")
        archive.mkdir(mode=0o700, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        previous = archive / f"{target.name}-{timestamp}"
        os.replace(target, previous)
        try:
            os.replace(stage, target)
        except BaseException:
            os.replace(previous, target)
            raise
        return previous
    finally:
        if stage.exists():
            shutil.rmtree(stage)
