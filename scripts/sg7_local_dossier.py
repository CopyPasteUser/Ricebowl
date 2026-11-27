#!/usr/bin/env python3
"""Build the SG7 exact-main dossier from local evidence, not the Actions API.

Hosted GitHub Actions are not used (docs/de-integration-governance.md), so
``scripts/sg7_exact_main_matrix.py`` -- which queries the hosted Actions API --
cannot produce acceptance evidence any more.  This tool replaces it with:

* a **committed, complete local CI receipt** for the exact main SHA
  (``docs/evidence/local-ci/<sha12>/receipt.json``), checked with
  ``scripts/local_ci.py validate_receipt`` against the whole step catalog
  (every step PASS, the dispatch-only GPU step may be BLOCKED);
* optionally the **two-session SG6 package comparison** report
  (``sg6-comparison.json`` from ``scripts/local_ci.sh --compare-sg6``); its
  presence or absence is reported and never invented;
* the open hardware / owner items, always listed as not certified.

The dossier is software evidence from an unsigned local receipt.  It never
claims hardware sign-off, never closes SG6/SG7 and is published write-once
(``sg7_dossier_io``).  Exit status: 0 dossier written and ready for formal
review, 1 dossier written but blocked, 2 nothing written (bad input).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import local_ci as lci
from sg7_dossier_io import DossierWriteError, publish_dossier, publish_text
from sg7_exact_main_matrix import CHECKS
from sg7_safe_receipt_io import ReceiptReadError, read_regular_bytes

REPO_ROOT = Path(__file__).resolve().parents[1]
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
RECEIPT_LIMIT = 4 << 20
COMPARISON_LIMIT = 64 << 10
SIGNOFF_LIMIT = 64 << 10
SG6_PACKAGES = (
    "ricebowl-wayland-core_0.1.0~preview2_all.deb",
    "ricebowl-wayland-session_0.1.0~preview3_all.deb",
    "ricebowl-riceplate-native_0.1.0~preview2_amd64.deb",
    "ricebowl-wayland-desktop_0.1.0~preview3_amd64.deb",
)

# SG7 acceptance area -> local CI steps that replace the hosted job step(s).
# Keys are the CHECKS codes of the hosted collector so both dossiers speak the
# same vocabulary; tests/test_sg7_local_dossier.py proves the two stay in sync
# and that every step id exists in the catalog.
LOCAL_AREAS: dict[str, tuple[str, ...]] = {
    "python-x11": ("py-compile", "py-tests", "x11-gtk-unit", "x11-luna-panel-capture",
                   "x11-hub-creator-smoke", "x11-shell-smoke", "x11-gallery", "components-tests"),
    "rust-test-clippy-build": ("shell-syntax", "py-native-unit", "rust-test", "rust-clippy", "rust-build"),
    "native-clean-elf": ("rust-repro",),
    "native-four-package-build": ("pkg-core-desktop",),
    "native-package-safety": ("pkg-verify-set",),
    "native-clean-worktree-rebuild": ("pkg-clean-rebuild",),
    "native-package-corruption": ("pkg-tamper",),
    "ubuntu-disposable-install-purge": ("pkg-docker-install",),
    "ubuntu-upgrade-downgrade-recovery": ("pkg-upgrade-rollback",),
    "native-headless-labwc": ("native-smoke",),
    "native-dynamic-rices": ("shared-engine-smoke",),
    "native-resource-growth": ("sg7-resource-receipts",),
    "native-session-crash-recovery": ("creator-teardown",),
    "native-xwayland": ("xwayland-taskbar",),
    "native-creator-dual-rices": ("creator-composers-render",),
    "wayland-session": ("session-boot",),
    "wayland-real-mako": ("mako111-real",),
    "portal-negative-unit": ("portal-unit",),
    "portal-pixman-repeated": ("portal-pixman-repeat",),
    "portal-crash-recovery": ("portal-crash-recovery",),
    "portal-strict-software-frame": ("portal-strict-frame",),
}

# Always listed, whatever the receipt says: local CI cannot certify these.
UNCERTIFIED = (
    "Hardware: physical Mint/ThinkPad login, DRM/GPU (the dispatch-only portal-gpu-frame step is "
    "not required and is BLOCKED without a render node), Flatpak consent, real Orca/IME sign-off",
    "Owner: .github/release-signoff-1.0.json hardware sign-off is separate and is never inferred from CI",
    "SG7: sustained idle CPU, long-running leak and cold-login latency on real hardware "
    "(local headless soak and three CI process-replacement cycles are not a hardware benchmark)",
    "SG1-SG5: full final integrated functionality/accessibility parity beyond the passing smokes",
    "Provenance: the local CI receipt is unsigned (no sigstore/OIDC attestation) and only as "
    "trustworthy as the host and the person who committed it",
    "SG6: two cloud sessions are not independent third-party builders; the Mint-compatible "
    "checks run in a local Docker container, not on Linux Mint hardware",
)


class _Duplicate(ValueError):
    pass


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise _Duplicate(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def _load_json(path: Path, limit: int) -> tuple[object, str]:
    """Bounded, no-follow read; returns the parsed JSON and the file's SHA-256."""
    data = read_regular_bytes(path, limit=limit)
    try:
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ReceiptReadError(f"{path.name} is not valid JSON: {exc}") from exc
    return obj, hashlib.sha256(data).hexdigest()


def committed_state(repo: Path, path: Path) -> bool | None:
    """True if ``path`` is tracked and byte-identical to HEAD; None if unknowable."""
    try:
        rel = path.resolve().relative_to(repo.resolve())
    except ValueError:
        return False
    try:
        tracked = subprocess.run(["git", "-C", str(repo), "ls-files", "--error-unmatch", "--", str(rel)],
                                 capture_output=True, text=True, timeout=30)
        if tracked.returncode:
            return False
        diff = subprocess.run(["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--", str(rel)],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return diff.returncode == 0


def _check_receipt(receipt: object, sha: str, catalog_ids: list[str]) -> list[str]:
    problems = [f"local CI receipt: {p}" for p in lci.validate_receipt(receipt, catalog_ids)]
    if isinstance(receipt, dict) and not problems:
        if receipt["sha"] != sha:
            problems.append(f"local CI receipt is for {receipt['sha']}, not the requested main SHA")
        if not receipt["complete"]:
            problems.append("local CI receipt is not complete (a step is not PASS, or the tree was dirty)")
        for rec in receipt["steps"]:
            if rec["status"] != "PASS" and rec["id"] not in lci.DISPATCH_ONLY:
                problems.append(f"local CI step {rec['id']} is {rec['status']}")
    return problems


def evaluate_comparison(report: object, sha: str, receipt: dict | None) -> tuple[str, list[str]]:
    """Return ("verified"|"invalid", problems) for an ``sg6-comparison.json`` payload."""
    problems: list[str] = []
    if not isinstance(report, dict):
        return "invalid", ["SG6 comparison is not a JSON object"]
    expect = {"schema_version": 1, "source_sha": sha, "software_ci_only": True,
              "hardware_accepted": False, "separate_runner_names_observed": True,
              "same_runner_os_and_build_tools": True,
              "independent_external_provenance_certified": False,
              "byte_identical_package_count": len(SG6_PACKAGES)}
    for key, value in expect.items():
        got = report.get(key)
        if type(got) is not type(value) or got != value:
            problems.append(f"SG6 comparison {key} is {got!r}, expected {value!r}")
    packages = report.get("packages")
    if (not isinstance(packages, dict) or set(packages) != set(SG6_PACKAGES)
            or not all(isinstance(v, str) and DIGEST_PATTERN.fullmatch(v) for v in packages.values())):
        problems.append("SG6 comparison packages are not the four expected .deb SHA-256 digests")
    elif receipt is not None:
        witness = receipt.get("artifacts", {}).get("sg6_packages")
        if witness and witness != packages:
            problems.append("SG6 comparison package digests differ from the full receipt's sg6_packages")
    return ("invalid" if problems else "verified"), problems


def build_report(*, sha: str, receipt: object, receipt_path: str, receipt_sha256: str,
                 receipt_committed: bool | None, comparison: object | None,
                 comparison_path: str, comparison_sha256: str | None,
                 comparison_read_error: str | None, release_signoff: dict,
                 checkout_catalog_sha256: str) -> dict:
    """Pure function: all evidence in, one dossier out; no I/O, no assumption of hardware."""
    if not SHA_PATTERN.fullmatch(sha):
        raise ValueError("Invalid main SHA")
    blockers: list[str] = []
    catalog_ids = [s.id for s in lci.CATALOG]
    blockers += _check_receipt(receipt, sha, catalog_ids)
    well_formed = isinstance(receipt, dict) and not any(b.startswith("local CI receipt:") for b in blockers)
    if receipt_committed is not True:
        blockers.append("local CI receipt is not committed (tracked and unmodified at HEAD)"
                        if receipt_committed is False else
                        "cannot confirm that the local CI receipt is committed")
    steps = receipt["steps"] if well_formed else []
    by_id = {r["id"]: r for r in steps}

    checks = []
    for code, workflow, job, step in CHECKS:
        local = LOCAL_AREAS.get(code, ())
        records = [by_id.get(sid) for sid in local]
        ok = bool(local) and all(r is not None and r["status"] == "PASS" for r in records)
        checks.append({
            "id": code, "status": "passed" if ok else "blocked",
            "workflow": workflow, "job": job, "step": step, "local_steps": list(local),
            "local_statuses": {sid: (r["status"] if r else "absent") for sid, r in zip(local, records)},
            "evidence_type": "local CI receipt step(s); not an independent or signed receipt"})
        if not ok:
            blockers.append(f"Not executed successfully in the local receipt: {code}")

    if comparison_read_error:
        cmp_status, cmp_problems = "invalid", [comparison_read_error]
    elif comparison is None:
        cmp_status, cmp_problems = "missing", []
    else:
        cmp_status, cmp_problems = evaluate_comparison(comparison, sha, receipt if well_formed else None)
    sg6 = {"status": cmp_status, "path": comparison_path, "file_sha256": comparison_sha256,
           "problems": cmp_problems,
           "detail": {
               "missing": "No two-session package comparison exists for this SHA. SG6 byte reproducibility "
                          "across two fresh sessions is NOT certified (run `scripts/local_ci.sh --compare-sg6`).",
               "verified": "Four .deb files byte-identical across two fresh local sessions with distinct runner "
                           "names (software evidence only; two cloud sessions are not independent builders).",
               "invalid": "The comparison report is present but does not verify; treated as not certified.",
           }[cmp_status]}
    local_ok = not blockers          # everything above concerns the local CI receipt only
    if cmp_status == "missing":
        blockers.append("SG6 two-session package comparison is missing for this SHA (not certified)")
    elif cmp_status == "invalid":
        blockers += [f"SG6 comparison: {p}" for p in cmp_problems]
    receipt_info: dict = {"path": receipt_path, "file_sha256": receipt_sha256,
                          "committed_and_unmodified": receipt_committed}
    if well_formed:
        pin = receipt["rust_toolchain_pin"]
        receipt_info.update({
            "sha": receipt["sha"], "commit_date": receipt["commit_date"], "complete": receipt["complete"],
            "counts": receipt["counts"], "step_count": len(steps),
            "dispatch_only_steps": {sid: by_id[sid]["status"] for sid in sorted(lci.DISPATCH_ONLY) if sid in by_id},
            "host": receipt["host"], "kernel": receipt["kernel"], "run_as": receipt["run_as"],
            "worker": receipt["worker"], "runner_name": receipt["runner_name"],
            "started_at": receipt["started_at"], "finished_at": receipt["finished_at"],
            "tree_clean": receipt["tree_clean"], "tree_clean_after_run": receipt["tree_clean_after_run"],
            "modified_tracked_files": receipt["modified_tracked_files"],
            "rust_toolchain_pin": pin,
            "catalog_sha256": receipt["catalog_sha256"],
            "checkout_catalog_sha256": checkout_catalog_sha256,
            "catalog_matches_checkout": receipt["catalog_sha256"] == checkout_catalog_sha256,
            "artifacts": receipt["artifacts"],
        })
    workflow_steps = [{"id": r["id"], "status": r["status"], "workflow": r["workflow"], "job": r["job"],
                       "step": r["step"], "script_sha256": r["script_sha256"], "log_sha256": r["log_sha256"]}
                      for r in steps]
    return {
        "schema_version": 1, "kind": "sg7-local-dossier", "source_sha": sha,
        "evidence_source": "local CI receipt (scripts/local_ci.sh); hosted GitHub Actions are not used",
        "software_ci_only": True, "physical_hardware_accepted": False,
        "formal_sg6_closed": False, "formal_sg7_closed": False,
        "local_ci_execution": "passed" if local_ok else "blocked",
        "sg6_two_session_comparison": sg6,
        "ready_for_formal_review": not blockers,
        "receipt": receipt_info,
        "checks": checks,
        "workflow_steps": workflow_steps,
        "workflow_steps_not_translated": [
            {"workflow": w, "job": j, "step": n, "reason": why} for w, j, n, why in lci.NOT_TRANSLATED],
        "release_signoff": release_signoff,
        "unverified_requirements": list(UNCERTIFIED) + (
            ["SG6: two-session package reproducibility (comparison report missing or not verified)"]
            if cmp_status != "verified" else []),
        "blockers": sorted(set(blockers)),
    }


def render_markdown(report: dict) -> str:
    r = report["receipt"]
    cmp_ = report["sg6_two_session_comparison"]
    passed = sum(1 for c in report["checks"] if c["status"] == "passed")
    out = [f"# SG7 local dossier for `{report['source_sha'][:12]}`", "",
           f"Source: `{report['source_sha']}`. Evidence: local CI receipt "
           f"(`{r['path']}`, SHA-256 `{r['file_sha256'][:16]}...`); hosted Actions are not used.", "",
           f"- Local CI execution: **{report['local_ci_execution']}**"
           + (f" ({r['counts']['PASS']} PASS, {r['counts']['BLOCKED']} BLOCKED, {r['counts']['FAIL']} FAIL; "
              f"complete={str(r['complete']).lower()}, dispatch-only: "
              + ", ".join(f"{k} {v}" for k, v in r['dispatch_only_steps'].items()) + ")" if "counts" in r else ""),
           f"- SG7 acceptance areas passed in the receipt: {passed}/{len(report['checks'])}",
           f"- SG6 two-session package comparison: **{cmp_['status']}**. {cmp_['detail']}",
           f"- Ready for formal review: **{str(report['ready_for_formal_review']).lower()}**; "
           "formal SG6/SG7 closed: false; physical hardware accepted: false",
           (f"- Receipt catalog `{r['catalog_sha256'][:12]}`; the checkout that generated this dossier has "
            f"`{r['checkout_catalog_sha256'][:12]}` ("
            + ("same catalog" if r["catalog_matches_checkout"] else
               "different: later commits changed local CI step scripts; the receipt's own per-step hashes apply")
            + ")" if "catalog_sha256" in r else "- Receipt catalog: unavailable (receipt did not validate)"),
           f"- Release sign-off JSON: `{report['release_signoff']['status']}` (never inferred from CI)", ""]
    if report["blockers"]:
        out += ["## Blockers", ""] + [f"- {b}" for b in report["blockers"]] + [""]
    out += ["## Not certified", ""] + [f"- {u}" for u in report["unverified_requirements"]] + [""]
    out += ["The complete machine-readable dossier (per-area and per-step results, step and script hashes, "
            "untranslated workflow steps) is the JSON file next to this one. This is unsigned software "
            "evidence from a local receipt, not hardware sign-off.", ""]
    return "\n".join(out)


def _release_signoff(repo: Path) -> dict:
    path = repo / ".github" / "release-signoff-1.0.json"
    try:
        obj, digest = _load_json(path, SIGNOFF_LIMIT)
        status = obj.get("status") if isinstance(obj, dict) else None
        return {"path": ".github/release-signoff-1.0.json", "status": status if isinstance(status, str) else "unreadable",
                "file_sha256": digest}
    except ReceiptReadError:
        return {"path": ".github/release-signoff-1.0.json", "status": "unreadable", "file_sha256": None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sha", required=True, help="exact main commit (40 hex) the dossier is for")
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help="repository root (default: this checkout)")
    parser.add_argument("--receipt", type=Path,
                        help="default: <repo>/docs/evidence/local-ci/<sha12>/receipt.json")
    parser.add_argument("--sg6-comparison", type=Path,
                        help="default: sg6-comparison.json next to the receipt; absence is reported, never faked")
    parser.add_argument("--output", type=Path, required=True, help="JSON dossier (write-once, 0600)")
    parser.add_argument("--markdown", type=Path, help="optional short Markdown summary (write-once)")
    args = parser.parse_args(argv)
    if not SHA_PATTERN.fullmatch(args.sha):
        print("SG7 local dossier: --sha must be a 40-hex commit id", file=sys.stderr)
        return 2
    repo = args.repo.resolve()
    receipt_path = args.receipt or repo / "docs" / "evidence" / "local-ci" / args.sha[:12] / "receipt.json"
    comparison_path = args.sg6_comparison or receipt_path.parent / "sg6-comparison.json"
    for target in (args.output, args.markdown):
        if target is not None and (target.is_symlink() or target.exists()):
            print(f"SG7 local dossier: refusing to overwrite {target}", file=sys.stderr)
            return 2
    try:
        receipt, receipt_sha256 = _load_json(receipt_path, RECEIPT_LIMIT)
    except ReceiptReadError as exc:
        print(f"SG7 local dossier: no usable local CI receipt for {args.sha[:12]}: {exc}", file=sys.stderr)
        return 2
    comparison = comparison_sha256 = comparison_error = None
    if comparison_path.is_symlink() or comparison_path.exists():
        try:
            comparison, comparison_sha256 = _load_json(comparison_path, COMPARISON_LIMIT)
        except ReceiptReadError as exc:
            comparison_error = f"SG6 comparison report unreadable: {exc}"

    def rel(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(repo))
        except ValueError:
            return str(path)

    try:
        report = build_report(
            sha=args.sha, receipt=receipt, receipt_path=rel(receipt_path), receipt_sha256=receipt_sha256,
            receipt_committed=committed_state(repo, receipt_path), comparison=comparison,
            comparison_path=rel(comparison_path), comparison_sha256=comparison_sha256,
            comparison_read_error=comparison_error, release_signoff=_release_signoff(repo),
            checkout_catalog_sha256=lci.catalog_digest())
        publish_dossier(args.output, report)
        if args.markdown is not None:
            publish_text(args.markdown, render_markdown(report))
    except (DossierWriteError, ValueError, OSError) as exc:
        print(f"SG7 local dossier: failed closed: {exc}", file=sys.stderr)
        return 2
    print(f"SG7 local dossier {args.sha[:12]}: local CI {report['local_ci_execution']}, "
          f"{sum(c['status'] == 'passed' for c in report['checks'])}/{len(report['checks'])} areas, "
          f"SG6 comparison {report['sg6_two_session_comparison']['status']}")
    for reason in report["blockers"]:
        print(f"BLOCKED: {reason}", file=sys.stderr)
    return 0 if report["ready_for_formal_review"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
