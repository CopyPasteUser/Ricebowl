#!/usr/bin/env python3
"""Read-only, fail-closed exact-main SG6/SG7 CI inventory.

Never equate a green workflow summary with individual executed acceptance
steps. This dossier is software CI evidence, not a release/hardware sign-off.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from check_release_workflows import (
    REQUIRED, REQUIRED_JOBS, WorkflowGateError, fetch_evidence,
    fetch_job_evidence, validate_runs, validate_jobs,
)
from sg7_evidence_snapshot import trusted_run_snapshot
from sg7_dossier_io import publish_dossier

# Exact step names are deliberately strict: renamed/skipped/missing acceptance
# steps must be reviewed and reflected in the dossier, never silently passed.
CHECKS = (
    ("python-x11", ".github/workflows/ci.yml", "test", "Validate and test the suite"),
    ("rust-test-clippy-build", ".github/workflows/riceplate-native.yml", "native-layer-shell", "Build and test native RicePlate"),
    ("native-clean-elf", ".github/workflows/riceplate-native.yml", "native-layer-shell", "Verify same-source native ELF reproducibility from a fresh target"),
    ("native-four-package-build", ".github/workflows/riceplate-native.yml", "native-layer-shell", "Package complete standalone Wayland app and aggregate desktop"),
    ("native-package-safety", ".github/workflows/riceplate-native.yml", "native-layer-shell", "Reject inconsistent or unsafe Wayland release packages"),
    ("native-clean-worktree-rebuild", ".github/workflows/riceplate-native.yml", "native-layer-shell", "Rebuild all four packages from clean tracked source"),
    ("native-package-corruption", ".github/workflows/riceplate-native.yml", "native-layer-shell", "Reject source-stamped but payload-tampered core package"),
    ("ubuntu-disposable-install-purge", ".github/workflows/riceplate-native.yml", "native-layer-shell", "Install, reinstall and purge complete preview in disposable Ubuntu"),
    ("ubuntu-upgrade-downgrade-recovery", ".github/workflows/riceplate-native.yml", "native-layer-shell", "Upgrade real previous Debian previews, reject corruption and roll back"),
    ("native-headless-labwc", ".github/workflows/riceplate-native.yml", "native-layer-shell", "Boot native Wayland layer surface"),
    ("native-dynamic-rices", ".github/workflows/riceplate-native.yml", "native-layer-shell", "Prove shared Rice engine across three native compositor-confirmed live layouts"),
    ("native-resource-growth", ".github/workflows/riceplate-native.yml", "native-layer-shell", "Verify SG7 compositor resource growth receipts at exact source SHA"),
    ("native-session-crash-recovery", ".github/workflows/riceplate-native.yml", "native-layer-shell", "Prove Creator teardown after real success and injected failures"),
    ("native-xwayland", ".github/workflows/riceplate-native.yml", "native-layer-shell", "Prove legacy XWayland application uses native RicePlate taskbar"),
    ("native-creator-dual-rices", ".github/workflows/riceplate-native.yml", "native-layer-shell", "Render two distinct Composer rices through native labwc"),
    ("wayland-session", ".github/workflows/wayland-session.yml", "session-smoke", "Boot actual labwc and Waybar headlessly"),
    ("wayland-real-mako", ".github/workflows/wayland-session.yml", "session-smoke", "Verify real source-locked Mako 1.11 notification arrivals in labwc"),
    ("portal-negative-unit", ".github/workflows/wayland-portal-strict.yml", "portal-unit", "Test negative paths and validate shell / Python syntax"),
    ("portal-pixman-repeated", ".github/workflows/wayland-portal-strict.yml", "portal-pixman-repeat", "Repeat existing pixman acceptance and verify no runtime leftovers"),
    ("portal-crash-recovery", ".github/workflows/wayland-portal-strict.yml", "portal-pixman-repeat", "Crash labwc before socket creation and verify runtime recovery"),
    ("portal-strict-software-frame", ".github/workflows/wayland-portal-strict.yml", "portal-strict-software-frame", "Strict no-DRM ScreenCast from real wlroots SHM frames to GStreamer"),
)

# These are explicitly out of scope of *this* CI job, not silently accepted.
# They require separate run receipts or genuinely different environments.
UNCERTIFIED = (
    "SG6: independent cross-host native ELF and four-package byte provenance",
    "SG6: all four components transitioning between two real package versions",
    "SG6: disposable Mint-compatible install/rollback proof",
    "SG7: sustained CPU/long-running leak evidence beyond three CI process-replacement cycles",
    "SG1-SG5: full final integrated functionality/accessibility parity",
    "Hardware: physical Mint/ThinkPad, GPU/Flatpak, real Orca/IME sign-off",
)
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
REPO_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def _unique_job(jobs: object, name: str, run_id: int, run_attempt: int) -> dict | None:
    if not isinstance(jobs, list) or len(jobs) > 1000:
        return None
    matching = [job for job in jobs if isinstance(job, dict) and job.get("name") == name]
    if len(matching) != 1:
        return None
    job = matching[0]
    if (type(job.get("run_id")) is not int or job["run_id"] != run_id
            or type(job.get("run_attempt")) is not int
            or job["run_attempt"] != run_attempt
            or job.get("status") != "completed" or job.get("conclusion") != "success"):
        return None
    return job


def evaluate(evidence: object, jobs_by_workflow: object, *, sha: str,
             main_sha: str, repository: str, open_prs: int) -> dict:
    """Pure validator: no network, no release writes, no assumption of hardware."""
    if (not SHA_PATTERN.fullmatch(sha) or not SHA_PATTERN.fullmatch(main_sha)
            or not REPO_PATTERN.fullmatch(repository)
            or type(open_prs) is not int or open_prs < 0):
        raise ValueError("Invalid exact-main dossier context")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("workflow_runs"), list):
        raise ValueError("Invalid Actions workflow evidence")
    if type(jobs_by_workflow) is not dict:
        raise ValueError("Invalid Actions job evidence")

    problems = []
    if sha != main_sha:
        problems.append("Checked-out SHA differs from live main; stale or racing main")
    if open_prs:
        problems.append(f"{open_prs} open PR(s); integrated-main sign-off deferred")
    selected = {}
    for path, expected_name in REQUIRED.items():
        allowed = ("push",) if path == ".github/workflows/ci.yml" else ("push", "workflow_dispatch")
        matches = [run for run in evidence["workflow_runs"] if isinstance(run, dict)
                   and run.get("path") == path and run.get("name") == expected_name
                   and run.get("head_sha") == sha and run.get("head_branch") == "main"
                   and run.get("event") in allowed and type(run.get("id")) is int
                   and run["id"] > 0]
        if matches:
            selected[path] = max(matches, key=lambda run: run["id"])
        else:
            problems.append(f"Missing trusted exact-main workflow: {path}")
    # Existing release verifier additionally enforces that no newer failed or
    # pending matching run can be hidden by an earlier success.
    if len(selected) == len(REQUIRED):
        try:
            ids = validate_runs(evidence, sha)
            validate_jobs(jobs_by_workflow, ids)
        except WorkflowGateError as exc:
            problems.append(str(exc))
    workflows = {}
    for path in REQUIRED:
        run = selected.get(path)
        workflows[path] = {
            "run_id": run["id"] if run else None,
            "url": f"https://github.com/{repository}/actions/runs/{run['id']}" if run else None,
            "event": run.get("event") if run else None,
            "status": run.get("status") if run else "missing",
            "conclusion": run.get("conclusion") if run else None,
            "head_sha": run.get("head_sha") if run else None,
        }
    checks = []
    for code, path, job_name, step_name in CHECKS:
        run = selected.get(path)
        job = (_unique_job(jobs_by_workflow.get(path), job_name,
                           run["id"], run.get("run_attempt"))
               if run else None)
        steps = job.get("steps") if job else None
        matching = ([step for step in steps if isinstance(step, dict) and step.get("name") == step_name]
                    if isinstance(steps, list) else [])
        ok = (run is not None and run.get("status") == "completed"
              and run.get("conclusion") == "success" and job is not None
              and len(matching) == 1 and matching[0].get("status") == "completed"
              and matching[0].get("conclusion") == "success")
        checks.append({"id": code, "status": "passed" if ok else "blocked",
                       "workflow": path, "job": job_name, "step": step_name,
                       "run_id": run["id"] if run else None,
                       "evidence_type": "GitHub Actions successful step; not an independent receipt"})
        if not ok:
            problems.append(f"Not executed successfully at exact main SHA: {code}")
    return {
        "schema_version": 1, "source_sha": sha, "main_sha": main_sha,
        "repository": repository, "software_ci_only": True,
        "physical_hardware_accepted": False, "formal_sg6_closed": False,
        "formal_sg7_closed": False,
        "exact_main_execution": "passed" if not problems else "blocked",
        "ready_for_formal_review": not problems,
        "workflows": workflows, "checks": checks,
        "unverified_requirements": list(UNCERTIFIED), "blockers": sorted(set(problems)),
    }


def _get_json(url: str, token: str) -> object:
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "RiceBowl-SG7-Matrix",
    })
    with urllib.request.urlopen(request, timeout=20) as stream:
        return json.load(stream)


def _live_context(repository: str, token: str) -> tuple[str, tuple[tuple[int, str, bool], ...]]:
    """Capture the actual open PR heads, not just their number.

    A PR can close while another opens, or be force-pushed, leaving the same
    count. Neither event may be hidden by a count-only context comparison.
    """
    prefix = f"https://api.github.com/repos/{repository}"
    main = _get_json(prefix + "/git/ref/heads/main", token)
    sha = main.get("object", {}).get("sha") if isinstance(main, dict) else None
    if not isinstance(sha, str) or not SHA_PATTERN.fullmatch(sha):
        raise ValueError("Live main ref does not contain a valid commit SHA")
    prs = _get_json(prefix + "/pulls?state=open&per_page=100", token)
    if not isinstance(prs, list) or len(prs) >= 100:
        raise ValueError("Open PR list unavailable or truncated")
    identities = []
    for pr in prs:
        if not isinstance(pr, dict):
            raise ValueError("Malformed live PR inventory")
        number, head, draft = pr.get("number"), pr.get("head"), pr.get("draft")
        head_sha = head.get("sha") if isinstance(head, dict) else None
        if (type(number) is not int or number <= 0
                or not isinstance(head_sha, str)
                or not SHA_PATTERN.fullmatch(head_sha) or type(draft) is not bool):
            raise ValueError("Untrusted live PR identity or head SHA")
        identities.append((number, head_sha, draft))
    if len(set(number for number, _, _ in identities)) != len(identities):
        raise ValueError("Duplicate PR in live inventory")
    return sha, tuple(sorted(identities))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    sha = os.environ.get("GITHUB_SHA", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    if (not SHA_PATTERN.fullmatch(sha) or not REPO_PATTERN.fullmatch(repo)
            or not token or args.output.is_symlink()):
        print("SG7: invalid or untrusted runner context", file=sys.stderr)
        return 2
    try:
        main_sha, open_pr_snapshot = _live_context(repo, token)
        evidence = fetch_evidence(repo, sha, token)
        initial_runs = trusted_run_snapshot(evidence, sha, REQUIRED)
        # The release-verifier selects all-or-nothing job identities; if any
        # workflow is missing we still output explicit per-check blockers.
        try:
            selected = validate_runs(evidence, sha)
            jobs = fetch_job_evidence(repo, selected, token)
        except WorkflowGateError:
            jobs = {}
        report = evaluate(evidence, jobs, sha=sha, main_sha=main_sha,
                          repository=repo, open_prs=len(open_pr_snapshot))
        # Jobs may finish, fail, or be rerun while their earlier green state
        # is being read. Refetch the trusted run identities and attempts:
        # final context checks alone do not detect same-main Actions races.
        current_runs = trusted_run_snapshot(fetch_evidence(repo, sha, token),
                                             sha, REQUIRED)
        if current_runs != initial_runs:
            raise ValueError("Trusted workflow run state changed during SG7 evidence collection")
        # Evidence collection makes several remote API requests. A merge or
        # newly opened PR during that interval invalidates the initial
        # main/PR snapshot, even when every retrieved Actions job was green.
        # Re-read both immediately before publishing any acceptance dossier.
        final_main_sha, final_open_pr_snapshot = _live_context(repo, token)
        if (final_main_sha, final_open_pr_snapshot) != (main_sha, open_pr_snapshot):
            raise ValueError("Live main or PR identity/head changed during SG7 evidence collection")
        publish_dossier(args.output, report)
    except (OSError, ValueError, urllib.error.URLError, WorkflowGateError) as exc:
        print(f"SG7: evidence collection failed closed: {exc}", file=sys.stderr)
        return 2
    print(f"SG7 exact-main checks: {sum(c['status'] == 'passed' for c in report['checks'])}/{len(report['checks'])}")
    for reason in report["blockers"]:
        print(f"BLOCKED: {reason}", file=sys.stderr)
    return 0 if report["ready_for_formal_review"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
