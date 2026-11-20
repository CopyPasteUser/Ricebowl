# SG6/SG7 exact-main CI evidence dossier (software-only)

**Never run this as the final sign-off before SG1–SG5 integration.** The
`SG7 exact-main evidence dossier` workflow is manual-only, on `main`, after
all intended integration merges. Its script checks live `main` against
`GITHUB_SHA`; it rejects any open PRs, absent workflows, stale/replaced runs,
missing jobs, skipped steps and duplicate step names. It never changes the
login, XFCE state, package installation or release sign-off JSON.

1. Integrate and review all owner-lane PRs through the integration lane.
2. Record the resulting immutable `main` SHA. Let the unfiltered Tests push
   workflow finish. If path filters did not schedule Native, Session or Strict
   Portal on that SHA, explicitly dispatch each from `main` and let it finish.
3. Run **SG7 exact-main evidence dossier** with workflow_dispatch on `main`.
   Download `sg7-exact-main-<sha>` and inspect `software-matrix.json`.
4. Require `exact_main_execution=passed`, `ready_for_formal_review=true`, no
   blocked checks, same SHA throughout and reviewed supporting full workflow
   logs and native resource receipts. All listed `unverified_requirements`
   remain open until separately evidenced. Do **not** close #417 or tag 1.0
   because this dossier is green.

The dossier binds each accepted claim to the **latest trusted main run** of
its named workflow and an **executed successful step** within the required
job, rather than to the run's aggregate green status alone. Acceptance labels
are explicitly job/step-derived, not independently verified per-feature
binary proofs. The existing release-source gate and CI's source-locked
rebuild/attestation tests remain authoritative for their own scope.

## Current gaps requiring separate engineering work

- Same-run clean-worktree reproducibility is **not** cross-host binary
  provenance. The four package control fields and staging digests cannot
  authenticate an externally supplied ELF. Independent build environments,
  locked inputs and binary comparison/attestation remain necessary.
- Current upgrade/downgrade coverage changes Core/Meta preview versions, not
  independent Native and Session binary revisions. Full four-component
  version transitions and `dpkg` interruption/repair should be audited with
  real, immutable versions and disposable roots.
- Ubuntu 24.04 CI is not a Mint 22 hardware sign-off; isolate any additional
  Mint-compatible software testing before claiming it.
- The three native `compare-replaced` cycles now check the previous
  RicePlate PID/start-time disappears, and record independent `/proc`
  utime+stime intervals alongside PSS/RSS/threads/FDs. The source-bound
  resource verifier validates each same-process CPU sample, its tick-rate
  arithmetic, absence of recycled PID evidence and all three cycle records.
  These **short headless CI observations** are not a sustained idle CPU,
  cold-login latency, long-running leak or real hardware benchmark. Collect
  longer-run and real-device evidence separately before SG7 acceptance.
- Strict software PipeWire pixels use a CI-private SHM portal backend. They
  do not certify DRM/GPU, Flatpak consent or the production wlr backend.

The workflow is intentionally **not** required in PR CI: it is a post-merge
snapshot, would be guaranteed to fail on PR heads and must not be run as a
fake exact-main check on an obsolete commit. All new collector unit tests
still run through the unfiltered Tests workflow on every PR.
