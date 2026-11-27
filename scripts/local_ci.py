#!/usr/bin/env python3
"""RiceBowl local CI: run every translated workflow test step on one exact SHA.

Hosted GitHub Actions are not used (docs/de-integration-governance.md).  This
runner replaces "exact-head CI" / "exact-main CI" with a *local CI receipt*:
it clones the exact commit fresh, runs the step catalog below strictly one
step at a time as an unprivileged user and records every result with log
hashes, tool versions and host identity in ``receipt.json``.

A receipt is ``complete`` only when the whole catalog ran on a clean checkout
and every step is PASS.  Missing tools are BLOCKED, never PASS.

Run it through ``scripts/local_ci.sh``; see docs/evidence/local-ci/README.md.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Sequence

SCHEMA_VERSION = 1
LOCAL_CI_VERSION = 1
PINNED_RUST = "1.88.0"
SG5_LABWC = "/opt/labwc-sg5"
SG5_LABWC_PIN = "b41af54a1bd7d9270d19de4c9a2b77d882cf3ede"
MAKO_VERSION = "1.11.0"
MAKO_COMMIT = "91c6b799855762ad1eb8b4498967c270a339be0c"

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
STEP_DIR = SCRIPT_DIR / "local_ci" / "steps"
DEFAULT_CACHE = Path(os.environ.get("LCI_CACHE_DIR", "/var/cache/ricebowl-local-ci"))
DEFAULT_USER = os.environ.get("LCI_RUN_USER", "rbdev")
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
STATUSES = ("PASS", "FAIL", "BLOCKED", "SKIPPED")
EXIT_BLOCKED = 77
SAFE_BASE_PATH = "/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
PASS_THROUGH_ENV = (
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "no_proxy", "all_proxy",
)


class LocalCIError(Exception):
    """Refusal or usage error (exit status 2)."""


# --------------------------------------------------------------------------
# Step catalog
# --------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Step:
    id: str
    timeout: int                      # runner-enforced cap, seconds
    tags: frozenset[str]
    needs: tuple[str, ...] = ()       # steps whose outputs this one consumes
    requires: tuple[str, ...] = ()    # preflight tokens (see Preflight)
    also: tuple[tuple[str, str, str], ...] = ()   # extra workflow steps covered

    @property
    def script(self) -> Path:
        return STEP_DIR / f"{self.id}.sh"


def _s(sid: str, timeout: int, tags: str, needs: str = "", requires: str = "",
       also: Sequence[tuple[str, str, str]] = ()) -> Step:
    return Step(sid, timeout, frozenset(tags.split()), tuple(needs.split()),
                tuple(requires.split()), tuple(also))


# Tool groups mirror the apt install lists of the hosted workflows.
X11 = "cmd:xvfb-run cmd:dbus-run-session py:gi py:PIL py:cairo"
WL = "cmd:labwc cmd:grim cmd:wlr-randr cmd:wtype cmd:swaybg cmd:foot cmd:fuzzel py:gi py:PIL"
RUST = "cmd:cargo cmd:rustc cmd:pkg-config pkgconfig:xkbcommon pkgconfig:dbus-1"
DEB = "cmd:dpkg-deb cmd:dpkg-shlibdeps cmd:readelf"
NATIVE = f"{RUST} {WL}"
PORTAL = "cmd:labwc cmd:pipewire cmd:grim cmd:gdbus py:gi file:/usr/libexec/xdg-desktop-portal"

# Execution order is the catalog order.  Timeouts are the workflow step's
# timeout-minutes when it has one; otherwise the largest internal `timeout`
# of the step plus a margin; otherwise the job's timeout (see README).
CATALOG: tuple[Step, ...] = (
    # --- static / unit (no compositor) ------------------------------------
    _s("py-compile", 600, "static"),
    _s("py-tests", 3600, "static unit"),
    _s("native-syntax", 600, "static"),
    _s("shell-syntax", 600, "static"),
    _s("py-native-unit", 1800, "static unit"),
    _s("sg7-matrix-unit", 480, "static unit"),
    _s("release-contract", 600, "static unit"),
    _s("release-workflows-unit", 600, "static unit"),
    _s("release-source-verify", 600, "static"),
    _s("release-source-archive", 600, "static"),
    _s("portal-unit", 480, "static unit", requires="py:gi"),
    _s("session-unit", 2100, "static unit", requires="cmd:dbus-run-session py:gi"),
    _s("ricespice-pulse", 300, "static", requires="cmd:pulseaudio cmd:pactl cmd:dbus-run-session"),
    _s("rust-fmt", 300, "static", requires="cmd:cargo cmd:rustfmt"),
    _s("rust-test", 3000, "static unit build", requires=RUST),
    _s("rust-clippy", 3000, "static build", requires=RUST + " cmd:cargo-clippy"),
    _s("rust-build", 3000, "static build", requires=RUST),
    _s("rust-repro", 3000, "static build", needs="rust-build", requires=RUST),
    _s("pkg-build", 2100, "static build packaging", requires=RUST + " " + DEB + " cmd:git"),
    # --- Python / GTK under Xvfb (X11, no compositor) ---------------------
    _s("x11-gtk-unit", 1800, "x11 unit", requires=X11),
    _s("x11-luna-panel-capture", 1800, "x11", requires=X11),
    _s("x11-hub-creator-smoke", 1800, "x11", requires=X11),
    _s("x11-shell-smoke", 1800, "x11", requires=X11 + " cmd:xfwm4"),
    _s("x11-gallery", 3600, "x11", requires=X11 + " cmd:xfwm4 cmd:thunar cmd:xdotool"),
    _s("components-tests", 1800, "x11 unit", requires=X11),
    # --- packaging chain (shares dist/riceplate-native-preview) -----------
    _s("pkg-preview-artifact", 600, "static packaging", needs="rust-build", requires=DEB),
    _s("pkg-native-deb", 600, "static packaging", needs="pkg-preview-artifact", requires=DEB),
    _s("pkg-session-deb", 600, "static packaging", needs="pkg-native-deb", requires=DEB),
    _s("pkg-core-desktop", 600, "static packaging", needs="pkg-session-deb", requires=DEB),
    _s("pkg-verify-set", 600, "static packaging", needs="pkg-core-desktop", requires=DEB),
    _s("pkg-clean-rebuild", 420, "static packaging", needs="pkg-verify-set", requires=DEB),
    _s("pkg-tamper", 420, "static packaging", needs="pkg-verify-set", requires=DEB),
    _s("pkg-source-identity", 300, "static packaging", needs="pkg-verify-set", requires=DEB),
    _s("pkg-docker-install", 1080, "docker packaging", needs="pkg-verify-set", requires="docker"),
    _s("pkg-upgrade-rollback", 1320, "docker packaging", needs="pkg-verify-set",
       requires="docker " + DEB + " cmd:git"),
    _s("mint-compat", 1500, "docker packaging", needs="pkg-verify-set", requires="docker"),
    # --- creator / analyzer unit tests ------------------------------------
    _s("creator-examples-validate", 600, "static unit"),
    _s("creator-supervisor-e2e", 600, "static unit"),
    _s("calendar-analyzer-unit", 600, "static unit"),
    _s("menu-analyzer-unit", 600, "static unit"),
    # --- labwc / Wayland compositor smokes ---------------------------------
    _s("sg4-creator-gtk-input", 210, "compositor",
       requires="cmd:labwc cmd:wtype cmd:wlr-randr cmd:grim py:gi py:PIL"),
    _s("sg1-sni", 225, "compositor", needs="rust-build", requires=NATIVE),
    _s("sg1-window-recovery", 210, "compositor", needs="rust-build", requires=NATIVE),
    _s("sg1-status", 360, "compositor", needs="rust-build", requires=NATIVE),
    _s("mako-build", 480, "build", requires="cmd:git cmd:meson cmd:ninja pkgconfig:wayland-client "
       "pkgconfig:pango pkgconfig:cairo pkgconfig:libsystemd pkgconfig:wayland-protocols"),
    _s("sg3-ricepop", 920, "compositor", needs="rust-build mako-build", requires=NATIVE),
    _s("sg1-interaction", 1020, "compositor", needs="rust-build", requires=NATIVE),
    _s("sg4-imported-rices", 420, "compositor", needs="rust-build", requires=NATIVE),
    _s("sg2-settings-gui", 540, "compositor", needs="rust-build", requires=NATIVE),
    _s("sg4-creator-gui-roundtrip", 960, "compositor", needs="rust-build", requires=NATIVE),
    _s("sg5-labwc-pin", 60, "static", requires=f"file:{SG5_LABWC}/labwc"),
    _s("sg5-atspi", 180, "compositor", needs="rust-build sg5-labwc-pin",
       requires=NATIVE + " py:pyatspi file:/usr/libexec/at-spi-bus-launcher"),
    _s("portal-smoke", 600, "compositor", requires=PORTAL),
    _s("native-smoke", 360, "compositor", needs="rust-build", requires=NATIVE),
    _s("shared-engine-smoke", 245, "compositor", needs="rust-build", requires=NATIVE),
    _s("sg7-resource-receipts", 600, "static", needs="shared-engine-smoke"),
    _s("windows-taskbar", 600, "compositor", needs="rust-build", requires=NATIVE),
    _s("luna-show-desktop", 190, "compositor", needs="rust-build", requires=NATIVE),
    _s("chrome-window-lifecycle", 190, "compositor", needs="rust-build", requires=NATIVE),
    _s("luna-autohide", 185, "compositor", needs="rust-build", requires=NATIVE),
    _s("xwayland-taskbar", 190, "compositor", needs="rust-build",
       requires=NATIVE + " cmd:Xwayland cmd:xterm"),
    _s("clipboard", 185, "compositor", needs="rust-build",
       requires=NATIVE + " cmd:Xwayland cmd:xclip cmd:wl-copy cmd:wl-paste"),
    _s("multioutput", 190, "compositor", needs="rust-build", requires=NATIVE),
    _s("creator-headless-render", 600, "compositor", needs="rust-build", requires=NATIVE),
    _s("creator-teardown", 600, "compositor", needs="rust-build", requires=NATIVE),
    _s("capture-validation", 600, "static", needs="native-smoke creator-headless-render",
       requires="py:PIL"),
    _s("luna-window-chrome", 200, "compositor", needs="rust-build", requires=NATIVE),
    _s("luna-hotkeys", 210, "compositor", needs="rust-build", requires=NATIVE),
    _s("creator-examples-render", 1200, "compositor", needs="rust-build", requires=NATIVE),
    _s("creator-composers-render", 320, "compositor", needs="rust-build", requires=NATIVE),
    _s("creator-handoff-render", 280, "compositor", needs="rust-build", requires=NATIVE),
    _s("creator-gtk-wayland", 215, "compositor",
       requires="cmd:labwc cmd:wtype cmd:wlr-randr cmd:grim py:gi py:PIL"),
    _s("portal-pixman-repeat", 720, "compositor", requires=PORTAL),
    _s("portal-crash-recovery", 720, "compositor", requires=PORTAL),
    _s("portal-strict-frame", 1800, "compositor",
       requires=PORTAL + " cmd:wireplumber file:/usr/libexec/xdg-desktop-portal-generic"),
    _s("portal-gpu-frame", 840, "compositor", requires=PORTAL + " drm",
       also=(("wayland-portal-strict.yml", "portal-gpu-frame",
              "Identify renderer and DRM prerequisites without modifying host drivers"),)),
    _s("session-deb", 600, "static packaging", requires="cmd:dpkg-deb"),
    _s("session-boot", 600, "compositor", requires=WL + " cmd:waybar cmd:swaylock cmd:Xwayland"),
    _s("mako111-real", 900, "compositor", requires=WL + " cmd:meson cmd:ninja"),
    _s("luna-settings-labwc", 300, "compositor", requires=WL),
)
CATALOG_BY_ID = {s.id: s for s in CATALOG}
assert len(CATALOG_BY_ID) == len(CATALOG), "duplicate step id"

# Workflow `run:` steps that are deliberately not translated, with the reason.
# tests/test_local_ci.py proves every other `run:` step is covered by a catalog
# entry, so a new workflow step cannot silently escape local CI.
NOT_TRANSLATED: tuple[tuple[str, str, str, str], ...] = (
    ("ci.yml", "test", "Install GTK introspection for Linux tests",
     "apt install on a disposable runner; replaced by the per-step tool preflight"),
    ("ci.yml", "publish-ricebowl", "Create release if absent",
     "creates a hosted GitHub Release with gh; local CI publishes nothing"),
    ("riceplate-native.yml", "sg4-creator-gtk-input",
     "Install only the GTK/headless Wayland keyboard dependencies", "apt install; replaced by preflight"),
    ("riceplate-native.yml", "native-layer-shell",
     "Install native Wayland and keyboard build dependencies", "apt install; replaced by preflight"),
    ("sg6-cross-runner.yml", "build", "Install native Debian build prerequisites",
     "apt install; replaced by preflight"),
    ("sg6-cross-runner.yml", "compare",
     "Require exact trusted checkout and compare four true package bytes",
     "needs the packages of two independent builders; run `local_ci.sh --compare-sg6 A B` "
     "on the two sessions' artifacts instead (also checks no hosted main ref)"),
    ("sg6-cross-runner.yml", "attest", "Require unchanged main before signing comparison",
     "sigstore/OIDC attestation is hosted-only; local receipts replace it"),
    ("sg7-exact-main.yml", "dossier", "Collect trusted exact-main workflow and job steps",
     "queries the hosted Actions API; the local receipt of the exact SHA replaces the dossier"),
    ("wayland-portal-strict.yml", "portal-unit", "Use signed public Ubuntu archive on this disposable runner",
     "rewrites apt mirrors with sudo; never done on the development host"),
    ("wayland-portal-strict.yml", "portal-unit", "Install Python GIO bindings for protocol tests",
     "apt install; replaced by preflight"),
    ("wayland-portal-strict.yml", "portal-pixman-repeat", "Use signed public Ubuntu archive on this disposable runner",
     "rewrites apt mirrors with sudo; never done on the development host"),
    ("wayland-portal-strict.yml", "portal-pixman-repeat", "Install disposable pixman compositor and portal runtime",
     "apt install; replaced by preflight"),
    ("wayland-portal-strict.yml", "portal-strict-software-frame",
     "Use signed public Ubuntu archive on this disposable runner",
     "rewrites apt mirrors with sudo; never done on the development host"),
    ("wayland-portal-strict.yml", "portal-strict-software-frame",
     "Install isolated software compositor and PipeWire development prerequisites",
     "apt install; replaced by preflight"),
    ("wayland-portal-strict.yml", "portal-strict-software-frame",
     "Repair only the disposable backend's invalid remote FD connection",
     "patches third-party source and only runs when GITHUB_ACTIONS=true; operator-installed backend instead"),
    ("wayland-portal-strict.yml", "portal-strict-software-frame",
     "Compile pinned third-party backend with CI-only private remote",
     "builds the third-party portal backend that is then installed system-wide; operator step"),
    ("wayland-portal-strict.yml", "portal-strict-software-frame",
     "Register backend only inside the disposable CI VM",
     "sudo-installs into /usr; done once per disposable container by scripts/local_ci/provision.sh "
     "(local CI itself never writes the host; portal-strict-frame is BLOCKED without it)"),
    ("wayland-portal-strict.yml", "portal-gpu-frame",
     "Install disposable compositor, portal, PipeWire and GStreamer", "apt install; replaced by preflight"),
    ("wayland-session.yml", "session-smoke", "Install native Wayland compositor and shell dependencies",
     "apt install (and apt-mirror rewrite); replaced by preflight"),
)

FIRST_WORKFLOW_STEP_SUFFIX = re.compile(r"\s*\[[^\]]*\]\s*$")


def step_mirrors(step: Step) -> tuple[str | None, str | None, str]:
    """(workflow file, job, step name) from the step script's `# Mirrors:` header."""
    for line in step.script.read_text(encoding="utf-8").splitlines()[:8]:
        m = re.match(r"# Mirrors: (\S+\.yml) / (.+?) / (.+)$", line)
        if m:
            return m.group(1), m.group(2), m.group(3)
        if line.startswith("# Mirrors: (none)"):
            return None, None, line[len("# Mirrors: "):]
    raise LocalCIError(f"step script {step.script.name} has no '# Mirrors:' header")


def covered_workflow_steps() -> set[tuple[str, str, str]]:
    covered: set[tuple[str, str, str]] = set()
    for step in CATALOG:
        wf, job, name = step_mirrors(step)
        if wf:
            covered.add((wf, job, FIRST_WORKFLOW_STEP_SUFFIX.sub("", name)))
        covered.update(step.also)
    return covered


# --------------------------------------------------------------------------
# Step selection
# --------------------------------------------------------------------------

def select_steps(spec: str | None, catalog: Sequence[Step] | None = None) -> tuple[list[str], set[str]]:
    """Resolve ``--steps`` to catalog-ordered ids plus auto-included prerequisites.

    ``spec`` is a comma list of step ids or ``@tag`` groups (``@static``,
    ``@compositor`` ...); ``None`` or ``all`` selects everything.  Unknown ids
    are an error; prerequisites a selected step consumes are added (and
    reported) so a subset run never silently depends on a skipped step.
    """
    catalog = CATALOG if catalog is None else catalog
    by_id = {s.id: s for s in catalog}
    if spec is None or spec.strip() in ("", "all"):
        return [s.id for s in catalog], set()
    chosen: set[str] = set()
    for token in (t.strip() for t in spec.split(",")):
        if not token:
            raise LocalCIError("empty step name in --steps")
        if token == "all":
            chosen.update(by_id)
        elif token.startswith("@"):
            members = [s.id for s in catalog if token[1:] in s.tags]
            if not members:
                raise LocalCIError(f"unknown step group: {token}")
            chosen.update(members)
        elif token in by_id:
            chosen.add(token)
        else:
            raise LocalCIError(f"unknown step id: {token}")
    explicit = set(chosen)
    stack = list(chosen)
    while stack:
        for need in by_id[stack.pop()].needs:
            if need not in chosen:
                chosen.add(need)
                stack.append(need)
    ordered = [s.id for s in catalog if s.id in chosen]
    return ordered, chosen - explicit


# --------------------------------------------------------------------------
# Receipt helpers (pure, unit-tested)
# --------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Steps whose hosted job runs only on an explicit workflow_dispatch input on
# special hardware (``portal-gpu-frame``: ``inputs.gpu`` on a self-hosted
# DRM runner).  A normal hosted run never executes them, so they do not gate
# ``complete``; they are still recorded (usually BLOCKED) in every receipt.
DISPATCH_ONLY = frozenset({"portal-gpu-frame"})


def is_complete(step_records: Sequence[dict], catalog_ids: Iterable[str], tree_clean: bool) -> bool:
    """Complete = clean checkout and every non-dispatch-only catalog step ran and passed."""
    by_id = {r["id"]: r for r in step_records}
    return bool(tree_clean) and all(
        sid in by_id and by_id[sid].get("status") == "PASS"
        for sid in catalog_ids if sid not in DISPATCH_ONLY)


def overall_exit_code(step_records: Sequence[dict]) -> int:
    """0 only if every *selected* (non-SKIPPED) step passed and at least one ran."""
    ran = [r for r in step_records if r["status"] != "SKIPPED"]
    return 0 if ran and all(r["status"] == "PASS" for r in ran) else 1


RECEIPT_KEYS = frozenset({
    "schema_version", "local_ci_version", "sha", "commit_date", "tree_clean",
    "tree_clean_after_run", "modified_tracked_files", "host", "kernel", "run_as",
    "tools", "rust_toolchain_pin", "worker", "runner_name", "started_at",
    "finished_at", "catalog_sha256", "selected_steps", "auto_included_steps",
    "counts", "complete", "steps", "artifacts",
})
STEP_KEYS = frozenset({
    "id", "workflow", "job", "step", "status", "exit_code", "duration_s",
    "log", "log_sha256", "script_sha256", "detail", "auto_included", "timeout_s",
})
TOOL_KEYS = frozenset({"rustc", "cargo", "python", "labwc", "labwc_sg5", "mako", "mako_1_11", "gtk"})


def validate_receipt(obj: object, catalog_ids: Sequence[str] | None = None) -> list[str]:
    """Return a list of schema/consistency problems (empty = well-formed)."""
    problems: list[str] = []
    if not isinstance(obj, dict):
        return ["receipt is not a JSON object"]
    missing = RECEIPT_KEYS - set(obj)
    extra = set(obj) - RECEIPT_KEYS
    if missing:
        problems.append(f"missing keys: {sorted(missing)}")
    if extra:
        problems.append(f"unexpected keys: {sorted(extra)}")
    if problems:
        return problems
    if obj["schema_version"] != SCHEMA_VERSION:
        problems.append("unsupported schema_version")
    if not isinstance(obj["sha"], str) or not SHA_RE.fullmatch(obj["sha"]):
        problems.append("sha is not a 40-hex commit id")
    for key in ("tree_clean", "tree_clean_after_run", "complete"):
        if type(obj[key]) is not bool:
            problems.append(f"{key} must be boolean")
    if not isinstance(obj["host"], dict) or not obj["host"].get("pretty_name"):
        problems.append("host.pretty_name missing")
    if not isinstance(obj["kernel"], str) or not obj["kernel"]:
        problems.append("kernel missing")
    tools = obj["tools"]
    if not isinstance(tools, dict) or not TOOL_KEYS <= set(tools):
        problems.append(f"tools must include {sorted(TOOL_KEYS)}")
    steps = obj["steps"]
    if not isinstance(steps, list) or not steps:
        problems.append("steps must be a non-empty list")
        return problems
    seen: set[str] = set()
    for rec in steps:
        if not isinstance(rec, dict) or set(rec) != STEP_KEYS:
            problems.append(f"malformed step record: {rec!r:.80}")
            continue
        if rec["id"] in seen:
            problems.append(f"duplicate step id: {rec['id']}")
        seen.add(rec["id"])
        if rec["status"] not in STATUSES:
            problems.append(f"{rec['id']}: bad status {rec['status']!r}")
        if rec["status"] in ("PASS", "FAIL"):
            if not isinstance(rec["log_sha256"], str) or not DIGEST_RE.fullmatch(rec["log_sha256"]):
                problems.append(f"{rec['id']}: PASS/FAIL needs a log sha256")
            if not isinstance(rec["exit_code"], int):
                problems.append(f"{rec['id']}: PASS/FAIL needs an exit code")
        if rec["status"] == "PASS" and rec["exit_code"] != 0:
            problems.append(f"{rec['id']}: PASS with non-zero exit code")
        if rec["status"] in ("BLOCKED", "SKIPPED") and not rec["detail"]:
            problems.append(f"{rec['id']}: {rec['status']} needs a reason")
    if catalog_ids is not None:
        absent = [sid for sid in catalog_ids if sid not in seen]
        if absent:
            problems.append(f"catalog steps absent from receipt: {absent}")
    ids = catalog_ids if catalog_ids is not None else [r["id"] for r in steps if isinstance(r, dict)]
    expected = is_complete([r for r in steps if isinstance(r, dict)], ids, bool(obj["tree_clean"]))
    if obj["complete"] != expected:
        problems.append(f"complete={obj['complete']} contradicts the step results")
    if obj["complete"] and any(r.get("status") != "PASS" for r in steps if isinstance(r, dict)):
        problems.append("complete receipt contains a non-PASS step")
    counts = obj["counts"]
    tally = {s: sum(1 for r in steps if isinstance(r, dict) and r.get("status") == s) for s in STATUSES}
    if counts != tally:
        problems.append(f"counts {counts} do not match steps {tally}")
    return problems


def render_summary(receipt: dict) -> str:
    out: list[str] = []
    out.append(f"# Local CI receipt for `{receipt['sha'][:12]}`")
    out.append("")
    verdict = "COMPLETE" if receipt["complete"] else "INCOMPLETE"
    out.append(f"**{verdict}** - every catalog step PASS on a clean exact checkout: "
               f"`{str(receipt['complete']).lower()}`")
    out.append("")
    c = receipt["counts"]
    out.append(f"- Commit: `{receipt['sha']}` ({receipt['commit_date']})")
    out.append(f"- Checkout clean at start: `{receipt['tree_clean']}`; "
               f"tracked files modified by the run: {len(receipt['modified_tracked_files'])}")
    out.append(f"- Result: {c['PASS']} PASS, {c['FAIL']} FAIL, {c['BLOCKED']} BLOCKED, {c['SKIPPED']} SKIPPED")
    out.append(f"- Host: {receipt['host'].get('pretty_name')} / kernel {receipt['kernel']} "
               f"(ran as `{receipt['run_as']}`, worker `{receipt['worker']}`)")
    out.append(f"- Started {receipt['started_at']}, finished {receipt['finished_at']}")
    pin = receipt["rust_toolchain_pin"]
    if not pin["matches"]:
        out.append(f"- WARNING: Rust toolchain {pin['actual']!r} differs from the workflows' pinned "
                   f"{pin['pinned']}; build/lint results are for the actual toolchain only.")
    out.append("- Tools: " + "; ".join(f"{k}={v}" for k, v in sorted(receipt["tools"].items()) if v))
    out.append("")
    out.append("| Step | Status | Seconds | Mirrors (workflow / job / step) |")
    out.append("| --- | --- | ---: | --- |")
    for rec in receipt["steps"]:
        mirror = " / ".join(x for x in (rec["workflow"], rec["job"], rec["step"]) if x) or "(local-only)"
        flag = " (auto)" if rec["auto_included"] else ""
        out.append(f"| `{rec['id']}`{flag} | {rec['status']} | {rec['duration_s']:.1f} | {mirror} |")
    notes = [r for r in receipt["steps"] if r["status"] in ("BLOCKED", "FAIL", "SKIPPED") and r["detail"]]
    if notes:
        out.append("")
        out.append("## Not passing")
        for rec in notes:
            out.append(f"- `{rec['id']}` {rec['status']}: {rec['detail']}")
    out.append("")
    out.append("Logs and SHA-256 of each log are in `receipt.json`; logs are local-only "
               "(`logs/` is git-ignored). Passing local CI is software evidence only: "
               "physical-device checks and hosted attestations remain separate.")
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Git / commit resolution
# --------------------------------------------------------------------------

def _git(repo: Path | str, *args: str, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess:
    # safe.directory=*: the runner (root) reads repositories owned by other users.
    cmd = ["git", "-c", "safe.directory=*", "-C", str(repo), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check, timeout=timeout)


def is_remote_repo(repo: str) -> bool:
    return "://" in repo or bool(re.match(r"^[\w.-]+@[\w.-]+:", repo))


def is_local_repo(repo: str) -> bool:
    return not is_remote_repo(repo) and Path(repo).exists()


def resolve_commit(repo: str, sha: str | None) -> tuple[str, str]:
    """Return (full 40-hex sha, commit date); refuse unknown or dirty sources.

    A dirty source tree is refused only when the requested commit is the
    checked-out HEAD: a receipt for "HEAD" while uncommitted edits exist
    would describe code that was not tested.  Explicit older SHAs are
    cloned from the object database and unaffected by working-tree edits.
    """
    if is_local_repo(repo):
        rev = sha or "HEAD"
        if rev.startswith("-"):
            raise LocalCIError(f"refusing option-like revision {rev!r}")
        try:
            full = _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").stdout.strip()
        except subprocess.CalledProcessError:
            raise LocalCIError(f"cannot resolve {rev!r} to a commit in {repo}") from None
        if not SHA_RE.fullmatch(full):
            raise LocalCIError(f"cannot resolve {rev!r} to a commit in {repo}")
        head = _git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False).stdout.strip()
        if head == full:
            dirty = _git(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip()
            if dirty:
                raise LocalCIError(
                    "refusing dirty source tree: HEAD has uncommitted tracked changes "
                    f"({len(dirty.splitlines())} paths); commit or stash them, or pass an explicit --sha")
        date = _git(repo, "show", "-s", "--format=%cI", full).stdout.strip()
        return full, date
    if not is_remote_repo(repo):
        raise LocalCIError(f"repository not found: {repo}")
    # Remote repository: only an exact 40-hex SHA can be pinned without trusting a moving ref.
    if not sha or not SHA_RE.fullmatch(sha):
        raise LocalCIError("a remote --repo requires an explicit full 40-hex --sha")
    return sha, ""


def prepare_clone(repo: str, sha: str, dest: Path, owner: str | None) -> str:
    """Fresh clone of exactly ``sha``; returns the commit date.  Refuses on any mismatch."""
    clone = subprocess.run(
        ["git", "-c", "safe.directory=*", "clone", "--quiet", "--no-checkout", "--no-hardlinks",
         "--", repo, str(dest)], capture_output=True, text=True, timeout=1800)
    if clone.returncode:
        raise LocalCIError(f"clone of {repo} failed: {clone.stderr.strip()[:300]}")
    # A shallow source makes git ignore --local and copy only branches/tags;
    # also carry the pinned historical baselines kept under refs/ci-baseline/.
    subprocess.run(["git", "-c", "safe.directory=*", "-C", str(dest), "fetch", "--quiet", "--no-tags",
                    "--", repo, "+refs/ci-baseline/*:refs/ci-baseline/*"],
                   capture_output=True, text=True, timeout=600)
    co = _git(dest, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", sha, check=False)
    if co.returncode:
        raise LocalCIError(f"commit {sha} is not present in {repo}: {co.stderr.strip()[:300]}")
    head = _git(dest, "rev-parse", "HEAD").stdout.strip()
    if head != sha:
        raise LocalCIError(f"clone HEAD {head} differs from requested {sha}")
    # Build products are not source: keep `git status` meaningful without editing tracked files.
    exclude = dest / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a", encoding="utf-8") as stream:
        stream.write("\n# local-ci build products\ntarget/\ndist/\n")
    if _git(dest, "status", "--porcelain").stdout.strip():
        raise LocalCIError("fresh clone is not clean")
    date = _git(dest, "show", "-s", "--format=%cI", "HEAD").stdout.strip()
    if owner and os.geteuid() == 0:
        subprocess.run(["chown", "-R", f"{owner}:", str(dest)], check=True)
    return date


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------

class Runner:
    """Runs commands as the unprivileged CI user (runuser when started as root)."""

    def __init__(self, user: str, env: dict[str, str]):
        self.user = user
        self.env = env
        self.drop = os.geteuid() == 0
        if self.drop:
            try:
                import pwd
                pwd.getpwnam(user)
            except KeyError:
                raise LocalCIError(f"unprivileged user {user!r} does not exist") from None
        else:
            import getpass
            self.user = getpass.getuser()

    def argv(self, command: Sequence[str], extra_env: dict[str, str] | None = None) -> list[str]:
        env = {**self.env, **(extra_env or {})}
        pairs = [f"{k}={v}" for k, v in sorted(env.items())]
        wrapped = ["env", "-i", *pairs, *command]
        return ["runuser", "-u", self.user, "--", *wrapped] if self.drop else wrapped

    def capture(self, command: Sequence[str], cwd: Path | None = None, timeout: int = 60,
                extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(self.argv(command, extra_env), cwd=str(cwd) if cwd else None,
                              capture_output=True, text=True, timeout=timeout)


class Preflight:
    """Tool checks standing in for the workflows' apt installs.  Cached per token."""

    def __init__(self, runner: Runner, cwd: Path):
        self.runner, self.cwd = runner, cwd
        self.cache: dict[str, str | None] = {}

    def check_token(self, token: str) -> str | None:
        """None if satisfied, else a short reason."""
        if token in self.cache:
            return self.cache[token]
        kind, _, arg = token.partition(":")
        if token == "docker":
            probe = ["docker", "info", "--format", "{{.ServerVersion}}"]
            reason = "docker daemon not reachable by the CI user (BLOCKED, never faked)"
        elif token == "drm":
            probe = ["sh", "-c", "ls /dev/dri/renderD* >/dev/null 2>&1"]
            reason = "no DRM render node (/dev/dri/renderD*)"
        elif kind == "cmd":
            probe = ["sh", "-c", f'command -v "{arg}" >/dev/null']
            reason = f"missing command: {arg}"
        elif kind == "py":
            probe = ["/usr/bin/python3", "-c", f"import {arg}"]
            reason = f"missing /usr/bin/python3 module: {arg}"
        elif kind == "file":
            probe = ["sh", "-c", f'test -e "{arg}"']
            reason = f"missing file: {arg}"
        elif kind == "pkgconfig":
            probe = ["pkg-config", "--exists", arg]
            reason = f"missing pkg-config package: {arg}"
        else:
            raise LocalCIError(f"unknown preflight token {token!r}")
        try:
            ok = self.runner.capture(probe, cwd=self.cwd, timeout=60).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        self.cache[token] = None if ok else reason
        return self.cache[token]

    def missing(self, step: Step) -> list[str]:
        return [r for r in (self.check_token(t) for t in step.requires) if r]


def read_os_release() -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                data[key.lower()] = value.strip().strip('"')
    except OSError:
        pass
    return {"id": data.get("id", ""), "version_id": data.get("version_id", ""),
            "pretty_name": data.get("pretty_name") or platform.platform()}


def catalog_digest(catalog: Sequence[Step] | None = None) -> str:
    catalog = CATALOG if catalog is None else catalog
    h = hashlib.sha256()
    for s in catalog:
        h.update(json.dumps([s.id, s.timeout, sorted(s.tags), s.needs, s.requires],
                            sort_keys=True).encode())
        h.update(sha256_file(s.script).encode())
    return h.hexdigest()


def collect_tools(runner: Runner, cwd: Path, cache_dir: Path) -> dict[str, str | None]:
    def first(command: Sequence[str]) -> str | None:
        try:
            res = runner.capture(command, cwd=cwd, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None
        text = (res.stdout or res.stderr).strip()
        return text.splitlines()[0] if res.returncode == 0 and text else None

    gtk = first(["/usr/bin/python3", "-c",
                 "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk; "
                 "print('GTK %d.%d.%d' % (Gtk.get_major_version(), Gtk.get_minor_version(), "
                 "Gtk.get_micro_version()))"])
    mako_dir = cache_dir / f"mako-{MAKO_VERSION}-src"
    mako_new = None
    head = mako_dir / ".git" / "HEAD"
    if (cache_dir / f"mako-{MAKO_VERSION}-build" / "mako").is_file() and head.is_file():
        mako_new = f"mako {MAKO_VERSION} source-locked {head.read_text().strip()[:12]}"
    return {
        "rustc": first(["rustc", "--version"]),
        "cargo": first(["cargo", "--version"]),
        "clippy": first(["cargo", "clippy", "--version"]),
        "rustfmt": first(["rustfmt", "--version"]),
        "python": first(["/usr/bin/python3", "--version"]),
        "labwc": first(["/usr/bin/labwc", "--version"]),
        "labwc_sg5": first([f"{SG5_LABWC}/labwc", "--version"]),
        "mako": first(["dpkg-query", "-W", "-f", "mako-notifier ${Version}", "mako-notifier"]),
        "mako_1_11": mako_new,
        "gtk": gtk,
        "docker": first(["docker", "--version"]),
        "dpkg_deb": first(["dpkg-deb", "--version"]),
        "meson": first(["meson", "--version"]),
    }


def rust_pin(rustc_version: str | None) -> dict:
    m = re.match(r"rustc (\d+\.\d+\.\d+)", rustc_version or "")
    actual = m.group(1) if m else None
    return {"pinned": PINNED_RUST, "actual": actual, "matches": actual == PINNED_RUST}


@dataclasses.dataclass
class Context:
    clone: Path
    work: Path
    out: Path
    runner: Runner
    sha: str
    cache: Path
    worker: str
    runner_name: str
    release_tag: str


def step_env(ctx: Context, shim: Path) -> dict[str, str]:
    env = {
        "PATH": f"{shim}:/root/.cargo/bin:{SAFE_BASE_PATH}",
        # A fresh HOME per run, like a fresh hosted runner: no state shared with the
        # developer's own session or with a concurrent smoke on the same host.
        "HOME": str(ctx.work / "home"),
        "USER": ctx.runner.user, "LOGNAME": ctx.runner.user,
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "dumb",
        "XDG_RUNTIME_DIR": "",
        "TMPDIR": str(ctx.work / "tmp"),
        "RUNNER_TEMP": str(ctx.work / "rt"),
        "GITHUB_SHA": ctx.sha,
        "GITHUB_WORKSPACE": str(ctx.clone),
        "RUNNER_NAME": ctx.runner_name,
        "ImageOS": "ubuntu" + read_os_release()["version_id"].split(".")[0],
        "ImageVersion": "local-" + (read_os_release()["version_id"] or "unknown"),
        "RUSTUP_HOME": os.environ.get("RUSTUP_HOME", "/root/.rustup"),
        "CARGO_HOME": os.environ.get("CARGO_HOME") or f"/home/{ctx.runner.user}/.cargo",
        "LOCAL_CI": "1",
        "LCI_CACHE": str(ctx.cache),
        "LCI_MAKO_BUILD": str(ctx.cache / f"mako-{MAKO_VERSION}-build"),
        "LCI_WORKER": ctx.worker,
    }
    if ctx.release_tag:
        env["LCI_RELEASE_TAG"] = ctx.release_tag
    for key in PASS_THROUGH_ENV:
        if key in os.environ:
            env[key] = os.environ[key]
    # Use the workflows' pinned Rust when it is installed, so build/lint
    # results match the pin instead of the host's default toolchain.
    pinned = Path(env["RUSTUP_HOME"]) / "toolchains" / f"{PINNED_RUST}-x86_64-unknown-linux-gnu"
    if "RUSTUP_TOOLCHAIN" in os.environ:
        env["RUSTUP_TOOLCHAIN"] = os.environ["RUSTUP_TOOLCHAIN"]
    elif pinned.is_dir():
        env["RUSTUP_TOOLCHAIN"] = PINNED_RUST
    ca = Path("/usr/local/share/rb-proxy-ca.crt")
    if ca.is_file():
        for key in ("SSL_CERT_FILE", "GIT_SSL_CAINFO", "CURL_CA_BUNDLE", "CARGO_HTTP_CAINFO",
                    "REQUESTS_CA_BUNDLE"):
            env[key] = str(ca)
    return env


def install_proxy_ca() -> None:
    """Same CA hand-off as /usr/local/bin/rb-run, so rbdev can use the agent proxy."""
    if os.geteuid() != 0:
        return
    for var in ("SSL_CERT_FILE", "GIT_SSL_CAINFO"):
        src = os.environ.get(var, "")
        if src and os.access(src, os.R_OK):
            dest = Path("/usr/local/share/rb-proxy-ca.crt")
            try:
                shutil.copyfile(src, dest)
                dest.chmod(0o644)
            except OSError:
                pass
            return


def terminate_group(proc: subprocess.Popen, grace: float = 5.0) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.killpg(proc.pid, 0)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(0.1)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def blocked_reason_from_log(log: Path) -> str:
    try:
        for line in reversed(log.read_text(encoding="utf-8", errors="replace").splitlines()):
            if line.startswith("LOCAL_CI_BLOCKED:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "step exited 77 (BLOCKED) without a stated reason"


def run_one(ctx: Context, step: Step, env: dict[str, str], log: Path) -> tuple[str, int | None, str, float]:
    """Execute the step script. Returns (status, exit code, detail, seconds)."""
    argv = ctx.runner.argv(["dbus-run-session", "--", "bash", "--noprofile", "--norc", "-e",
                            str(ctx.work / "steps" / step.script.name)], env)
    started = time.monotonic()
    with log.open("wb") as stream:
        stream.write(f"# local-ci step {step.id}\n# started {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
                     f"# cwd {ctx.clone}\n# timeout {step.timeout}s\n".encode())
        stream.flush()
        proc = subprocess.Popen(argv, cwd=str(ctx.clone), stdout=stream, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        timed_out = False
        try:
            code = proc.wait(timeout=step.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_group(proc)
            code = 124
            proc.wait()
        except BaseException:                   # SIGINT/SIGTERM to the runner: leave no compositor behind
            terminate_group(proc)
            raise
        else:
            terminate_group(proc, grace=1.0)    # no leaked compositors/daemons between steps
        stream.write(f"\n# exit {code}{' (runner timeout)' if timed_out else ''}\n".encode())
    seconds = time.monotonic() - started
    if timed_out:
        return "FAIL", 124, f"runner timeout after {step.timeout}s", seconds
    if code == 0:
        return "PASS", 0, "", seconds
    if code == EXIT_BLOCKED:
        return "BLOCKED", code, blocked_reason_from_log(log), seconds
    return "FAIL", code, "", seconds


def record(step: Step, status: str, exit_code: int | None, seconds: float, log: Path | None,
           detail: str, auto: bool) -> dict:
    wf, job, name = step_mirrors(step)
    return {
        "id": step.id, "workflow": wf, "job": job, "step": name, "status": status,
        "exit_code": exit_code, "duration_s": round(seconds, 2),
        "log": f"logs/{log.name}" if log and log.exists() else None,
        "log_sha256": sha256_file(log) if log and log.exists() else None,
        "script_sha256": sha256_file(step.script), "detail": detail,
        "auto_included": auto, "timeout_s": step.timeout,
    }


def collect_artifacts(ctx: Context, results: dict[str, dict]) -> dict:
    artifacts: dict = {"sg6_worker": None, "sg6_packages": {}, "preview_packages": {}}
    sg6 = ctx.clone / "dist" / "sg6"
    if results.get("pkg-build", {}).get("status") == "PASS" and sg6.is_dir():
        dest = ctx.out / "artifacts" / "sg6"
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        for item in sorted(sg6.iterdir()):
            if item.is_file() and not item.is_symlink():
                shutil.copy2(item, dest / item.name)
        artifacts["sg6_worker"] = ctx.worker
        artifacts["sg6_packages"] = {p.name: sha256_file(p) for p in sorted(dest.glob("*.deb"))}
    preview = ctx.clone / "dist" / "riceplate-native-preview"
    if preview.is_dir():
        artifacts["preview_packages"] = {p.name: sha256_file(p) for p in sorted(preview.glob("*.deb"))
                                         if p.is_file() and not p.is_symlink()}
    return artifacts


def execute(args: argparse.Namespace, repo: str, sha: str, commit_date: str, out: Path) -> int:
    ids, auto = select_steps(args.steps)
    install_proxy_ca()
    base = Path(tempfile.mkdtemp(prefix="rbci.", dir=args.tmp_base))
    base.chmod(0o755)
    try:
        return _execute(args, repo, sha, out, ids, auto, base)
    finally:
        if args.keep:
            print(f"local-ci: kept work dir {base}", file=sys.stderr)
        else:
            shutil.rmtree(base, ignore_errors=True)


def _execute(args: argparse.Namespace, repo: str, sha: str, out: Path, ids: list[str],
             auto: set[str], base: Path) -> int:
    ctx_user = args.user
    clone = base / "src"
    commit_date = prepare_clone(repo, sha, clone, ctx_user)
    work = base
    for sub in ("rt", "tmp", "steps", "home"):
        (work / sub).mkdir()
    for step in CATALOG:
        shutil.copy2(step.script, work / "steps" / step.script.name)
    shim = work / "bin"
    shim.mkdir()
    for name in ("python3", "python"):
        (shim / name).symlink_to("/usr/bin/python3")
    cache = args.cache_dir
    runner_name = args.runner_name or "local-ci-" + re.sub(r"[^A-Za-z0-9_.-]", "-", platform.node())
    probe_runner = Runner(ctx_user, {})
    if os.geteuid() == 0:
        subprocess.run(["chown", "-R", f"{probe_runner.user}:", str(work)], check=True)
        cache.mkdir(parents=True, exist_ok=True)
        subprocess.run(["chown", f"{probe_runner.user}:", str(cache)], check=True)
    else:
        cache.mkdir(parents=True, exist_ok=True)
    ctx = Context(clone, work, out, probe_runner, sha, cache, args.worker, runner_name,
                  args.release_tag or "")
    runner = Runner(ctx_user, step_env(ctx, shim))
    ctx.runner = runner
    preflight = Preflight(runner, clone)
    out.mkdir(parents=True, exist_ok=True)
    logs = out / "logs"
    shutil.rmtree(logs, ignore_errors=True)
    logs.mkdir()
    (out / ".gitignore").write_text("logs/\nartifacts/\n", encoding="utf-8")
    tools_start = collect_tools(runner, clone, cache)
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    results: dict[str, dict] = {}
    records: list[dict] = []
    total = len(ids)
    failed_fast = False
    selected = set(ids)
    for index, step in enumerate(CATALOG, 1):
        sid = step.id
        if sid not in selected:
            records.append(record(step, "SKIPPED", None, 0.0, None, "not selected by --steps", False))
            continue
        auto_flag = sid in auto
        position = sum(1 for s in CATALOG[:index] if s.id in selected)
        if failed_fast:
            rec = record(step, "SKIPPED", None, 0.0, None, "skipped by --fail-fast after an earlier failure", auto_flag)
        else:
            unmet = [f"{n}={results[n]['status']}" for n in step.needs
                     if n not in results or results[n]["status"] != "PASS"]
            missing = preflight.missing(step) if not unmet else []
            if unmet:
                rec = record(step, "BLOCKED", None, 0.0, None,
                             "prerequisite step not PASS: " + ", ".join(unmet), auto_flag)
            elif missing:
                rec = record(step, "BLOCKED", None, 0.0, None, "; ".join(missing), auto_flag)
            else:
                log = logs / f"{sid}.log"
                print(f"[{position}/{total}] {sid} ...", flush=True)
                status, code, detail, seconds = run_one(ctx, step, step_env(ctx, shim), log)
                rec = record(step, status, code, seconds, log, detail, auto_flag)
        results[sid] = rec
        records.append(rec)
        extra = f" - {rec['detail']}" if rec["detail"] else ""
        print(f"[{position}/{total}] {sid}: {rec['status']} ({rec['duration_s']:.1f}s){extra}", flush=True)
        if rec["status"] == "FAIL":
            tail = (logs / f"{sid}.log").read_text(errors="replace").splitlines()[-15:]
            print("    " + "\n    ".join(tail), flush=True)
            if args.fail_fast:
                failed_fast = True
    tools_end = collect_tools(runner, clone, cache)
    tools = {k: tools_end.get(k) or tools_start.get(k) for k in tools_end}
    modified = [l[3:] for l in _git(clone, "status", "--porcelain", "--untracked-files=no").stdout.splitlines()]
    finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    artifacts = collect_artifacts(ctx, results)
    commit_date = commit_date or ""
    receipt = {
        "schema_version": SCHEMA_VERSION, "local_ci_version": LOCAL_CI_VERSION,
        "sha": sha, "commit_date": commit_date,
        "tree_clean": True,               # prepare_clone refuses anything else
        "tree_clean_after_run": not modified, "modified_tracked_files": modified,
        "host": read_os_release(), "kernel": platform.release() + " " + platform.version(),
        "run_as": runner.user, "tools": tools, "rust_toolchain_pin": rust_pin(tools.get("rustc")),
        "worker": args.worker, "runner_name": runner_name,
        "started_at": started_at, "finished_at": finished_at,
        "catalog_sha256": catalog_digest(), "selected_steps": ids,
        "auto_included_steps": sorted(auto),
        "counts": {s: sum(1 for r in records if r["status"] == s) for s in STATUSES},
        "steps": records, "artifacts": artifacts,
    }
    receipt["complete"] = is_complete(records, [s.id for s in CATALOG], True)
    problems = validate_receipt(receipt, [s.id for s in CATALOG])
    if problems:
        raise LocalCIError("internal error: invalid receipt: " + "; ".join(problems))
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "summary.md").write_text(render_summary(receipt), encoding="utf-8")
    c = receipt["counts"]
    print(f"local-ci: {sha[:12]} {c['PASS']} PASS, {c['FAIL']} FAIL, {c['BLOCKED']} BLOCKED, "
          f"{c['SKIPPED']} SKIPPED; complete={str(receipt['complete']).lower()}; receipt {out / 'receipt.json'}")
    return overall_exit_code(records)


# --------------------------------------------------------------------------
# Auxiliary commands
# --------------------------------------------------------------------------

def print_list() -> None:
    width = max(len(s.id) for s in CATALOG)
    print(f"{len(CATALOG)} steps, executed sequentially in this order (@tag selects a group):")
    for s in CATALOG:
        wf, job, name = step_mirrors(s)
        mirror = f"{wf} / {job} / {name}" if wf else name
        tags = ",".join(sorted(s.tags))
        needs = f" needs={','.join(s.needs)}" if s.needs else ""
        print(f"  {s.id:<{width}}  {s.timeout:>5}s  [{tags}]{needs}\n  {'':<{width}}  -> {mirror}")
    print("\nWorkflow steps NOT translated (and why):")
    for wf, job, name, why in NOT_TRANSLATED:
        print(f"  {wf} / {job} / {name}\n      {why}")


def verify_receipt(path: Path) -> int:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"local-ci: cannot read receipt: {exc}", file=sys.stderr)
        return 2
    problems = validate_receipt(obj, [s.id for s in CATALOG])
    logs = path.parent / "logs"
    if logs.is_dir():
        for rec in obj.get("steps", []):
            if rec.get("log") and (path.parent / rec["log"]).is_file():
                if sha256_file(path.parent / rec["log"]) != rec.get("log_sha256"):
                    problems.append(f"{rec['id']}: log hash mismatch")
    for p in problems:
        print(f"local-ci: receipt problem: {p}", file=sys.stderr)
    if not problems:
        state = "complete" if obj["complete"] else "NOT complete"
        print(f"local-ci: receipt for {obj['sha'][:12]} is well-formed and {state}")
    return 0 if not problems and obj["complete"] else 1


def compare_sg6(args: argparse.Namespace, repo: str, sha: str, out: Path) -> int:
    dir_a, dir_b = (Path(p).resolve() for p in args.compare_sg6)
    for d in (dir_a, dir_b):
        if not d.is_dir() or d.is_symlink():
            raise LocalCIError(f"not an ordinary directory: {d}")
    base = Path(tempfile.mkdtemp(prefix="rbci.", dir=args.tmp_base))
    base.chmod(0o755)
    try:
        clone = base / "src"
        prepare_clone(repo, sha, clone, None)
        root = base / "comparison"
        for worker, src in (("host-a", dir_a), ("host-b", dir_b)):
            shutil.copytree(src, root / worker, symlinks=False)
        report = base / "report.json"
        res = subprocess.run([sys.executable, "scripts/verify_sg6_cross_runner.py", "compare",
                              "--directory", str(root), "--source-sha", sha, "--output", str(report)],
                             cwd=str(clone), capture_output=True, text=True)
        sys.stderr.write(res.stderr)
        if res.returncode:
            return 1
        out.mkdir(parents=True, exist_ok=True)
        dest = out / "sg6-comparison.json"
        shutil.copyfile(report, dest)
        data = json.loads(report.read_text())
        print(f"local-ci: SG6 comparison OK for {sha[:12]}: {data['byte_identical_package_count']} "
              f"byte-identical packages; report {dest}")
        return 0
    finally:
        if not args.keep:
            shutil.rmtree(base, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="local_ci.sh",
        description="Run the translated hosted-CI steps on one exact SHA and write a local CI receipt.",
        epilog="Exit status: 0 all selected steps PASS; 1 a step is FAIL/BLOCKED; 2 usage or refusal.")
    p.add_argument("--sha", help="commit to test (default: HEAD of --repo; must be clean)")
    p.add_argument("--repo", default=str(REPO_ROOT if (REPO_ROOT / ".git").exists() else "/home/user/Ricebowl"),
                   help="repository path or URL to clone (default: the repository this script lives in)")
    p.add_argument("--steps", help="comma list of step ids or @tag groups (default: all)")
    p.add_argument("--list", action="store_true", help="list steps, their workflow mirrors and exclusions")
    p.add_argument("--out", help="output directory (default: <repo>/docs/evidence/local-ci/<sha12>)")
    p.add_argument("--worker", choices=("host-a", "host-b"), default="host-a",
                   help="SG6 worker identity recorded by pkg-build (two sessions use host-a and host-b)")
    p.add_argument("--runner-name", help="runner identity for SG6 receipts (default: local-ci-<hostname>)")
    p.add_argument("--release-tag", help="also run check_release_contract.py for this tag")
    p.add_argument("--fail-fast", action="store_true", help="mark remaining steps SKIPPED after the first FAIL")
    p.add_argument("--keep", action="store_true", help="keep the temporary clone for debugging")
    p.add_argument("--user", default=DEFAULT_USER, help=argparse.SUPPRESS)
    p.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE, help=argparse.SUPPRESS)
    p.add_argument("--tmp-base", default="/var/tmp", help=argparse.SUPPRESS)
    p.add_argument("--verify-receipt", type=Path, metavar="RECEIPT",
                   help="validate an existing receipt.json (schema, completeness, log hashes) and exit")
    p.add_argument("--compare-sg6", nargs=2, metavar=("HOST_A_DIR", "HOST_B_DIR"),
                   help="compare the artifacts/sg6 directories of two sessions (pkg-build --worker host-a / host-b)")
    return p


def default_out(repo: str, sha: str) -> Path:
    base = Path(repo) if is_local_repo(repo) else Path.cwd()
    return base / "docs" / "evidence" / "local-ci" / sha[:12]


def _interrupt(signum: int, _frame: object) -> None:
    raise KeyboardInterrupt(f"signal {signum}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    previous = None
    if threading.current_thread() is threading.main_thread():
        previous = signal.signal(signal.SIGTERM, _interrupt)   # let `finally` remove the temp clone
    try:
        if args.list:
            print_list()
            return 0
        if args.verify_receipt:
            return verify_receipt(args.verify_receipt)
        select_steps(args.steps)          # fail early on unknown ids
        sha, commit_date = resolve_commit(args.repo, args.sha)
        out = Path(args.out) if args.out else default_out(args.repo, sha)
        if args.compare_sg6:
            return compare_sg6(args, args.repo, sha, out)
        return execute(args, args.repo, sha, commit_date, out)
    except LocalCIError as exc:
        print(f"local-ci: refused: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("local-ci: interrupted; no receipt written", file=sys.stderr)
        return 130
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
