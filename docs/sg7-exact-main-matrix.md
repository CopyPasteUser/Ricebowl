# SG6/SG7 exact-main evidence dossier (software-only)

Hosted GitHub Actions are not used (owner decision, 27 November 2026; see
[de-integration-governance.md](de-integration-governance.md)). The dossier is
therefore built from **local evidence** by `scripts/sg7_local_dossier.py`, not
from the Actions API. It never changes the login, XFCE state, package
installation or release sign-off JSON, and it is software evidence only.

## Producing the dossier (final main SHA)

1. Integrate and review all owner-lane work, then record the immutable `main`
   SHA. Run `scripts/local_ci.sh` on that exact SHA and commit
   `docs/evidence/local-ci/<sha12>/receipt.json` + `summary.md` (see the
   [local CI receipts](evidence/local-ci/README.md)).
2. Optionally build the four packages in two fresh sessions and compare them
   (`scripts/local_ci.sh --compare-sg6 A B --out docs/evidence/local-ci/<sha12>`),
   and commit the resulting `sg6-comparison.json` next to the receipt.
3. Generate the dossier (write-once, mode 0600; it refuses to overwrite):

   ```sh
   python3 scripts/sg7_local_dossier.py --sha <40-hex main SHA> \
       --output docs/evidence/sg7/<sha12>.json --markdown docs/evidence/sg7/<sha12>.md
   ```

   Exit status: `0` ready for formal review, `1` written but blocked, `2`
   nothing written (no usable receipt, bad SHA, existing output).
4. Read `local_ci_execution`, `sg6_two_session_comparison.status`,
   `blockers`, `unverified_requirements` and the per-area `checks`. Do **not**
   close the remaining SG1-SG5/SG7 items in #417 or tag 1.0 because the
   dossier is green.

What it checks, fail-closed:

- The receipt is read with the bounded, no-follow reader (`sg7_safe_receipt_io`:
  `O_NOFOLLOW`/`O_NONBLOCK`, regular file, size cap, inode re-check), rejects
  duplicate JSON keys, and must be **committed and unmodified** at `HEAD`.
- `scripts/local_ci.py validate_receipt` against the current whole step
  catalog: its `sha` must equal the requested main SHA, `complete` must be true
  and re-derived from the steps, every catalog step must be present and PASS.
  Only the dispatch-only `portal-gpu-frame` step (a manual, self-hosted-DRM
  hosted job) may be BLOCKED.
- The 21 SG7 acceptance areas (same codes as the former hosted collector) map
  to the local steps that mirror them (`LOCAL_AREAS`); an area passes only if
  all its steps are PASS in the receipt. Every receipt step is listed with its
  mirrored workflow/job/step and script/log hashes, and the workflow steps
  that local CI deliberately does not translate are listed with their reason.
- The optional `sg6-comparison.json` is reported as `missing`, `verified` or
  `invalid` (same SHA, four expected `.deb` digests, matches the receipt's
  `sg6_packages`, distinct runner names, no hardware/external-provenance
  claim). It is never created or implied; **while it is missing or invalid
  `ready_for_formal_review` is false**.
- Open hardware and owner items are always listed as not certified;
  `physical_hardware_accepted`, `formal_sg6_closed` and `formal_sg7_closed` are
  always `false`. The receipt is unsigned (no sigstore/OIDC attestation) and is
  only as trustworthy as the host and the person committing it.

Dossier for main `1b10db5`: [JSON](evidence/sg7/1b10db548ba1.json),
[summary](evidence/sg7/1b10db548ba1.md). Local CI passed (79 PASS, the
dispatch-only GPU step BLOCKED), 21/21 areas pass, **SG6 two-session
comparison missing** (not run yet), so it is not ready for formal review.

## Retired hosted path and what was ported from draft PR #596

`scripts/sg7_exact_main_matrix.py` and `.github/workflows/sg7-exact-main.yml`
remain as the hosted-Actions collector, but they are not the evidence source
under the current policy and are listed as not translated in local CI. Their
unit tests still run in the `sg7-matrix-unit` local step.

Draft PR #596 (left untouched for its owner) hardened that collector. What
stays valid without hosted Actions was ported:
`scripts/sg7_safe_receipt_io.py` (bounded no-follow reads, used by
`verify_sg7_resource_receipts.py` and the local dossier) and
`scripts/sg7_dossier_io.py` (atomic write-once 0600 publication, used by the
resource verifier, the collector and the local dossier), with their tests.
**Not ported:** `sg7_evidence_snapshot.py` and the live open-PR/main pinning,
which protect against races between Actions API reads; with a committed
receipt for one immutable SHA there is no such race, and the "open PRs"
condition is a merge-process rule (governance), not receipt content.

## Scope boundaries and remaining SG7 work

- **SG6 software-only gate is closed** (historical, from the hosted-Actions era; for later SHAs the local
  two-session comparison above replaces it) in [issue #417](https://github.com/CopyPasteUser/Ricebowl/issues/417)
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
