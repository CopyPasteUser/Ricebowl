"""Bounded, owner-private lineage receipts for immutable Creator draft files.

Recipes remain the source of truth. Each new draft gets a separate no-overwrite
receipt binding its semantic fingerprint to its parent. Legacy drafts without
receipts remain readable, but cannot claim a verified predecessor.
"""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from . import recipes

HISTORY_VERSION = 1
MAX_HISTORY_DEPTH = 64
# Existing Creator versions use random hex, but accept older safe draft-*.json
# basenames as parents so that upgrading does not strand their edit history.
_DRAFT_NAME = re.compile(r"draft-[A-Za-z0-9][A-Za-z0-9._-]{0,95}\.json\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_KINDS = frozenset(("create", "import", "save", "fork", "upgrade", "recover"))
_ROOT_KINDS = frozenset(("create", "import"))


class HistoryError(ValueError):
    """Damaged or unverifiable private Creator version history."""


def _receipt_path(draft: Path) -> Path:
    if not draft.is_absolute() or _DRAFT_NAME.fullmatch(draft.name) is None:
        raise HistoryError("Creator history requires a canonical private draft filename")
    return draft.with_suffix(".history")


def _valid_hash(value: Any) -> bool:
    return type(value) is str and _SHA.fullmatch(value) is not None


def write(draft: Path, digest: str, *, kind: str,
          parent: tuple[str, str] | None = None) -> None:
    """Publish a durable version intent before making its recipe visible."""
    receipt = _receipt_path(draft)
    if (kind not in _KINDS or not _valid_hash(digest)
            or (parent is None) != (kind in _ROOT_KINDS)):
        raise HistoryError("Invalid Creator version receipt")
    if parent is not None and (type(parent[0]) is not str
                               or _DRAFT_NAME.fullmatch(parent[0]) is None
                               or not _valid_hash(parent[1])
                               or parent[0] == draft.name):
        raise HistoryError("Invalid Creator version parent")
    data = {"history_version": HISTORY_VERSION, "kind": kind,
            "target_semantic_sha256": digest,
            "parent": ({"filename": parent[0], "semantic_sha256": parent[1]}
                       if parent is not None else None)}
    payload = (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()
    try:
        recipes._write_private_new(receipt, payload, suffix=".history")
        # The receipt must survive a crash before the matching recipe becomes
        # visible; otherwise a power loss could expose an unverified version.
        dirfd = os.open(receipt.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except OSError as exc:
        raise HistoryError("Creator version history intent could not be saved safely") from exc


def _read_receipt(draft: Path, digest: str | None) -> dict[str, Any] | None:
    """Validate a bounded intent; digest=None is reserved for recovery inspection."""
    receipt = _receipt_path(draft)
    try:
        descriptor = os.open(receipt, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None  # Older Creator drafts predate persistent history.
    except OSError as exc:
        raise HistoryError("Creator history receipt cannot be opened safely") from exc
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077 or metadata.st_size > 2048):
            raise HistoryError("Creator history receipt has unsafe permissions or size")
        payload = stream.read(2049)
    try:
        data = json.loads(payload.decode("utf-8"),
                          object_pairs_hook=recipes._object_without_duplicates)
    except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
        raise HistoryError("Creator history receipt contains invalid JSON") from exc
    if (not isinstance(data, dict)
            or set(data) != {"history_version", "kind", "target_semantic_sha256", "parent"}
            or type(data["history_version"]) is not int
            or data["history_version"] != HISTORY_VERSION
            or type(data["kind"]) is not str or data["kind"] not in _KINDS
            or not _valid_hash(data["target_semantic_sha256"])
            or (digest is not None and data["target_semantic_sha256"] != digest)):
        raise HistoryError("Creator history fingerprint or version does not match this draft")
    parent = data["parent"]
    if (parent is None) != (data["kind"] in _ROOT_KINDS):
        raise HistoryError("Creator history parent is inconsistent")
    if parent is not None and (
            not isinstance(parent, dict) or set(parent) != {"filename", "semantic_sha256"}
            or type(parent["filename"]) is not str
            or _DRAFT_NAME.fullmatch(parent["filename"]) is None
            or parent["filename"] == draft.name
            or not _valid_hash(parent["semantic_sha256"])):
        raise HistoryError("Creator history parent is invalid")
    return data


def read(draft: Path, digest: str) -> dict[str, Any] | None:
    """Verify a version receipt against its actually parsed recipe fingerprint."""
    return _read_receipt(draft, digest)


def inspect_intent(draft: Path) -> dict[str, Any] | None:
    """Inspect a receipt without trusting a possibly missing or corrupt recipe."""
    return _read_receipt(draft, None)
