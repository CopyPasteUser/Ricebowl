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
   remain open until separately evidenced. Do **not** close the remaining SG1–SG5/SG7 items in #417 or tag 1.0
   because this dossier is green.

**Context-race hardening (23 November 2026):** the collector reads the
live `main` commit and **every open PR number, HEAD SHA and Draft flag**
*twice*: before querying Actions and again after all workflow/job evidence
has been evaluated. If either snapshot changes
during collection, it fails closed **without writing a dossier**. This
narrows the stale-result window but is not an atomic GitHub transaction;
no report may bypass the later exact-source review or hardware gates.

The dossier binds each accepted claim to the **latest trusted main run** of
its named workflow and an **executed successful step** within the required
job, rather than to the run's aggregate green status alone. Acceptance labels
are explicitly job/step-derived, not independently verified per-feature
binary proofs. The existing release-source gate and CI's source-locked
rebuild/attestation tests remain authoritative for their own scope.

## Scope boundaries and remaining SG7 work

- **SG6 software-only gate is closed** in [issue #417](https://github.com/CopyPasteUser/Ricebowl/issues/417)
  at [`main@344d5557`](https://github.com/CopyPasteUser/Ricebowl/commit/344d5557a749213dfdd83be2db4a5ba21e8b2624).
  [Tests #44881618535](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44881618535),
  [Native/Ubuntu/Mint #44881618473](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44881618473)
  and [cross-runner #44881618480](https://github.com/CopyPasteUser/Ricebowl/actions/runs/44881618480)
  succeeded on that source, with signed [comparison report](https://github.com/CopyPasteUser/Ricebowl/attestations/70471969)
  and [four package subjects](https://github.com/CopyPasteUser/Ricebowl/attestations/70471973).
  This SG7 dossier does **not** re-evaluate SG6's separately reviewed receipts.
  Hosted-runner repeatability is not external machine/toolchain certification.
  After further merges, the pinned SG6 receipts are historical, not proof
  that all release workflows passed a new exact-final-main SHA.
- Real Native and Session **historical package versions** now participate
  in reversible, dependency-safe installed upgrades and downgrades with
  interrupted `dpkg` repair; see [#559](https://github.com/CopyPasteUser/Ricebowl/pull/559)
  and [#563](https://github.com/CopyPasteUser/Ricebowl/pull/563).
  This separately accepted SG6 result is not imported into SG7 execution checks.
- The independent disposable Linux Mint **22.1 Xia** four-package
  installation/reinstallation/corrupt-archive/recovery/purge matrix exists
  ([#562](https://github.com/CopyPasteUser/Ricebowl/pull/562)).
  This is software compatibility, **not** Mint/ThinkPad GPU or physical
  login/hardware sign-off. Verify its result on the *final main SHA*
  for later exact-final-main release review; SG6's software acceptance is
  already documented at the pinned SHA.
- The SG7 resource verifier now reads each raw cycle JSON and CPU receipt
through a bounded, no-follow descriptor instead of a separate pathname
check followed by `Path.read_bytes()`. It rejects directories, FIFOs,
symlinks, oversized files and in-flight size/metadata changes without
blocking on special files. The new standard-library helper has independent
negative Linux tests; this is integrity hardening for **software-only
receipts**, not a source signature, proof of their measurement origin or a
physical system benchmark. Full repository and compositor tests are still
required for acceptance.

The three native `compare-replaced` cycles now check the previous
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
