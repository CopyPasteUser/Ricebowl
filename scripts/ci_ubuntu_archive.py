#!/usr/bin/python3
"""Use Ubuntu's signed public archive instead of a stuck EC2 regional mirror.

GitHub's ephemeral Ubuntu 24.04 runner sometimes spends the full 28-minute
Wayland install budget downloading dozens of packages from its region-local
EC2 mirror. This edits *only* that runner's archive URI, not apt trust,
distribution/suites, security.ubuntu.com, packages, or the user's machine.
"""
from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path


SOURCES = Path("/etc/apt/sources.list.d/ubuntu.sources")
_EC2_ARCHIVE = re.compile(
    r"http://[a-z0-9-]+\.ec2\.archive\.ubuntu\.com/ubuntu(?=/|\s|$)"
)
_PUBLIC_ARCHIVE = "https://archive.ubuntu.com/ubuntu"
_SIGNED_BY = "/usr/share/keyrings/ubuntu-archive-keyring.gpg"
# GitHub runner images occasionally ship ubuntu.sources with Ubuntu archive
# entries disabled. apt-get update then succeeds against third-party repos
# alone, while every genuine Ubuntu package is "Unable to locate". Restore
# only the missing official Noble suites, using the existing Ubuntu keyring.
_REQUIRED = (
    ("noble", _PUBLIC_ARCHIVE),
    ("noble-updates", _PUBLIC_ARCHIVE),
    ("noble-security", "https://security.ubuntu.com/ubuntu"),
)
_UBUNTU_HOST = re.compile(
    r"https?://(?:archive|security)\.ubuntu\.com/ubuntu/?$"
    r"|https?://[a-z0-9-]+\.ec2\.archive\.ubuntu\.com/ubuntu/?$"
)


def _active_suites(content: str) -> set[str]:
    """Find enabled, signed Ubuntu deb822 stanzas; ignore disabled sources."""
    found: set[str] = set()
    for stanza in re.split(r"\n\s*\n", content):
        fields: dict[str, str] = {}
        for line in stanza.splitlines():
            if not line or line.startswith("#") or line[0].isspace() or ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key.lower()] = value.strip()
        if (fields.get("enabled", "yes").lower() in ("no", "false", "0")
                or "deb" not in fields.get("types", "").split()
                or fields.get("signed-by") != _SIGNED_BY
                or not any(_UBUNTU_HOST.fullmatch(uri)
                           for uri in fields.get("uris", "").split())
                or not {"main", "universe"}.issubset(
                    set(fields.get("components", "").split()))):
            continue
        found.update(fields.get("suites", "").split())
    return found


def restore_missing_noble_sources(content: str) -> str:
    """Append only missing official signed Ubuntu suites; never alter third-party sources."""
    have = _active_suites(content)
    missing = [(suite, uri) for suite, uri in _REQUIRED if suite not in have]
    if not missing:
        return content
    stanzas = [
        ("Types: deb\n"
         f"URIs: {uri}\n"
         f"Suites: {suite}\n"
         "Components: main restricted universe multiverse\n"
         f"Signed-By: {_SIGNED_BY}\n")
        for suite, uri in missing
    ]
    return content.rstrip() + "\n\n" + "\n".join(stanzas)


def rewrite_sources(text: str) -> str:
    """Replace only Ubuntu's EC2 archive endpoint; leave trust/other repos alone."""
    return _EC2_ARCHIVE.sub(_PUBLIC_ARCHIVE, text)


def update_runner_sources(path: Path = SOURCES) -> bool:
    """Atomic one-file update; fail closed if the expected .sources is unsafe."""
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.geteuid() != 0:
        raise RuntimeError("Ubuntu mirror selection is restricted to root in GitHub Actions")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
        raise RuntimeError("Unexpected runner Ubuntu archive source file")
    current = path.read_text(encoding="utf-8")
    changed = restore_missing_noble_sources(rewrite_sources(current))
    if changed == current:
        return False
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".ubuntu-sources-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as dest:
            os.fchmod(dest.fileno(), stat.S_IMODE(info.st_mode))
            dest.write(changed)
            dest.flush()
            os.fsync(dest.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


if __name__ == "__main__":
    print("Signed Ubuntu Noble archives verified/restored" if update_runner_sources()
          else "Signed Ubuntu Noble archives already configured")
