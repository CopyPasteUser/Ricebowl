# RiceBowl DE 1.0 – integration contract

> Scope: experimental native labwc/Wayland DE only. XFCE/X11 stays the supported
> default. This document governs **parallel changes**; it is not a release
> certificate. Always inspect current GitHub state before acting on the snapshot.

## Integration authority and sources of truth

- `main` is the sole stable integration base; never merge directly from a
  stale checkout or override concurrent commits.
- [AGENTS.md](../AGENTS.md) defines architectural/safety constraints;
  [RICEBOWL_DE_ROADMAP.md](../RICEBOWL_DE_ROADMAP.md) defines functional targets;
  [RELEASE_1_0_GATES.md](../RELEASE_1_0_GATES.md) defines release sign-off.
- Each lane works on its own branch and submits a **draft PR**. GitHub PR
  descriptions/comments are asynchronous hand-offs, not proof of behavior.
- Only the integration lane makes reviewed merges into `main`; no agent
  should automatically merge another lane's PR.
- This applies equally to unattended RiceBowl development automations.
  Their existing schedules are not controlled by this document. Operators must
  coordinate those automations before enabling concurrent write access.

## Four development lanes and integration lane

| Lane | Owns | Boundary |
| --- | --- | --- |
| **core** | `input_core.rs`, desktop keyboard focus/seat policy, foreign-toplevel window registry/actions, shared surface/event lifecycle | Does not implement file operations or rice-specific menu UI |
| **desktop** | Native XDG Desktop inventory, selection/layout/positions, file operations and RiceField hand-off | Uses core input/focus API; does not independently own compositor grabs |
| **system** | `macrice/de/session.py`, `settings_backend.py`, `wayland_displays.py`, `display_restore.py`, OS services and portals | Backends may expose capabilities but may not redesign the GTK settings UI |
| **shell** | `native_menu.rs`, `menu_chrome.rs`, `recipe.rs`, `macrice/de/settings.py`, Creator and RicePack/UI contracts | No duplicate NetworkManager/BlueZ/PipeWire/window-management backends |
| **integration** | Shared interface contracts, PR review, head-SHA CI, merge order, performance/release QA and this governance file | No opportunistic concurrent feature rewrite |

**Collision-prone paths:** `components/riceplate-wayland/src/main.rs`,
`macrice/de/session.py`, `macrice/de/settings.py`,
`components/riceplate-wayland/src/recipe.rs`,
`.github/workflows/riceplate-native.yml`, and
`scripts/smoke_riceplate_native.sh`. An owner may use their assigned path,
but every concurrent change to these paths requires coordination in the PR
description with the other affected lane(s). `main.rs` glue should be
small and reviewed by integration, while behavior lives in owned modules.

**Cross-lane feature request protocol:**

1. Open a GitHub issue/PR comment defining the **type signature, state machine,
   error states, security boundary and intended call sites**.
2. Wait for the owning lane to supply the API (or explicitly transfer the
   single-file ownership for a limited change).
3. Base stacked work on the owning PR only when necessary; clearly state the
   parent branch and dependency in the PR body.
4. Never silently cherry-pick/duplicate unmerged private branch behavior.
5. Rebase/retarget only after the parent lands and rerun CI for the new head.

## Live integration dependency graph (snapshot: 2026-11-14; check current refs)

> Verified against GitHub on 14 November, after the original review; this
> is an *evidence snapshot*, not an atomic branch lock. [Issue #360](https://github.com/CopyPasteUser/Ricebowl/issues/360)
> tracks subsequent handoffs. #367/#370 are now CLOSED, not merged; #366,
> #368 and #371 remain Draft. Frozen code blobs are valid even when PRs close.

```text
main @ 559f800ead46ff60c6551624734d4bbe47ddf667 [unchanged at snapshot]
├── #366 Run keyboard/pointer fix — integration-owned
│   fix/luna-run-pointer-caret-20261114 @ bb16551fed7c318968867bc31ce5e46fce3fe975
│   previous head 12eb4193 Tests/Native PASS; newest head Clippy CI pending
├── #367 Core lease/seat — CLOSED UNMERGED; FROZEN source
│   sprint/de-core-focus-20261114 @ 8947a569612c8258ddeb6949ad8e74ee42a43798
│   Tests PASS 43579110004; Native PASS 43579109980
├── #370 Desktop inventory/inotify — CLOSED UNMERGED; FROZEN source
│   sprint/de-desktop-files-20261114 @ e588c2edc337c30e2f23dcfb9ab755ced88724a1
│   Tests PASS 43580321303; Native PASS 43580321268
├── #368 System strict portals — EXCLUSIVELY SYSTEM-OWNED
│   sprint/de-system-portals-20261114 @ 52713f797d2aec6c47f490a7e9f7d3d654cb8d36
│   Tests/Native/Strict FAILED; DRM-backed frame acceptance not passed
├── #369 Integration governance documentation
│   integration/de-governance-snapshot-20261114 [this PR; docs only]
└── #371 Integration runtime assembly — separate candidate, NOT READY
    integration/de-runtime-assembly-20261114 @ 23fd50d266d906263e9378776dd0f75edb3d9fc0
    exact module inputs: #367 @ 8947a569612c and #370 @ e588c2edc337
    main.rs file surfaces, inotify + temporary Core focus overlay;
    first new native build FAILED E0502, later E2E focus FAIL; newest CI pending
```

Original feature PRs #367/#370 are frozen and must never be rewritten by
integration. Seven exact file blobs from those heads were assembled in the
initial commit of #371 (`de6f2c239b720d28b3ae51855b1e0e0fd6a67ab1`),
without touching either source branch. A green modular CI is **not**
evidence of an interactive desktop: #371 must prove real XDG layer surfaces,
file actions, inotify, temporary compositor focus and return to normal
Wayland/XWayland clients via headless labwc with real input and `grim`.

**#366 root cause established with real captures:** earlier `grim` Run
restoration compared the same text/caret (`chars=4, caret=4`) with and
without the compositor-drawn mouse pointer over the field. Captured crop
`bbox=(21,12,37,32)` accounts for the 130 changed pixels. The fix moves
the **real** pointer into neutral dialog space after actual caret placement,
without changing the original pixel assertions or bypassing `wtype`.
[Native exact-head PASS](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43582896711),
[Tests PASS](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43582896633).
This is headless software acceptance, not physical Mint/IME/Orca QA.

**#371 current status at this snapshot:** the first integration patch wired
file surfaces and callback/reactor paths but [Native](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43583190211)
failed Rust E0502 from an immutable snapshot borrow overlapping redraw.
The borrow regression was fixed; intermediate combined Native CI subsequently
ran real headless labwc. External XDG file creation triggered a genuine
4,848-pixel framebuffer change, and the regular file double-click operated,
but [Native](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43584560681)
FAILED because the temporary keyboard focus had no compositor-confirmed
`wl_keyboard.enter`. A later patch changed the focus overlay's input-region
policy and added redacted seat diagnostics; its exact-head CI is pending.
The context UI, robust focus return to regular applications, file drag/move,
dual-output/hotplug and hardware/IME acceptance remain open.

### Ownership and controlled sequence

- **Integration owns only** `main.rs`, `luna_dialog.rs`,
  `scripts/smoke_riceplate_native.sh`, shared CI, this governance
  document, guarded merges and isolated assembly branches. Core/Desktop
  maintain their own modules on new stacked branches; System alone owns #368.
- #366 may be considered for a guarded merge only after exact final head,
  relevant CI, Clippy/build and review requirements are independently
  satisfied; recheck head immediately before mutation, then verify new
  `main` push workflows before the next merge.
- #371 is a combined candidate that must pass end-to-end checks **as a
  whole**; do not merge disjoint unit-green #367/#370 and claim a file
  desktop is finished. Retime/rebase new stacked Core/Desktop branches only
  after their accepted parent integration.
- #368 remains isolated and **unmergeable** without an actually delivered
  PipeWire frame in strict mode on a compatible runner. Hosted pixman
  isolation response=2 does not count as success.
- All PRs need exact head/base SHAs, complete file scope, review resolution,
  rollback and a hardware-unverified marker. A GitHub comment is not a
  transactionally enforced lock.

Older #342/#343/#349/#352/#353/#355/#356/#357/#361 are closed, not merged:
they are not current parents and must not be revived implicitly.

## Mandatory PR pre-merge checklist

For a candidate `head_sha` and the contemporaneous `main_sha`:

- [ ] Fetch exact head/base SHAs, full diff, changed paths, stack parents and
  status of the PR; inspect outdated docs and competing changes.
- [ ] Check owner boundaries, shared hotspots, all upstream dependencies,
  branch ancestry, reviews and unresolved discussions.
- [ ] Review Wayland protocol and D-Bus/IPC/resource lifecycle; reject
  stale window proxies, unbounded waits, shell interpolation and untrusted
  filesystem traversal. Confirm no global XFCE settings are changed.
- [ ] **Exact-head** Tests, native Rust tests, Clippy, release build and genuine
  labwc smoke all pass when affected. Wayland session/packaging/recovery tests
  must pass for session/package changes. A check from an intermediate commit,
  another PR, or just a green merge button does not count.
- [ ] For UI/input changes, inspect genuine `grim` outputs and verify
  interactions (pointer *and* keyboard), geometry, output/mixed-DPI and
  accessibility boundaries. Screenshots alone do not establish function.
- [ ] Corrupted config, missing provider, cancellation, crashed child,
  rollback and X11/XFCE non-regression covered by relevant tests.
- [ ] **Re-read the head SHA immediately before merge**, use GitHub's
  expected-head-SHA guard, and reject if it moved.
- [ ] After merge, fetch the **new main SHA** and verify full appropriate
  workflows on that exact SHA. If regression occurs, investigate and revert
  the offending change, not the tests.
- [ ] Keep physical Mint hardware/IME/Orca/real GPU/portal acceptance
  outstanding until traceable on-device evidence exists.

If a change is doc-only and has no runtime or CI effect, explicitly record
that limited scope and still require valid merge ancestry, review and exact-head
tests appropriate to the change. Never bypass a failing **relevant** gate.

## Performance and release evidence

Track actual `labwc`, native RicePlate, Mako, swayidle, optional Waybar and
on-demand RiceSpice PSS/RSS, CPU time/wakeups, startup and session shutdown.
Measure whole-session and per-process cost on the same physical machine,
including cold start, repeated rice switching, two outputs and long-running
idle. Report hardware/kernel, display configuration and exact commit SHA.
Headless CI timings and screenshot-script wall time are **not** hardware
performance benchmarks. Extra resident helpers require measured benefit
and verified cleanup.

Release status is binary by gate, never a made-up percentage. The mandatory
real-device list in `RELEASE_1_0_GATES.md` stays open until independently
performed and recorded. The 1.0 sign-off JSON must not be marked approved
on CI evidence alone.

## Concurrent writers and scheduled automation

At the 14 November preflight, task automation **RiceBowl Wayland
weiterentwickeln** (`Automation_ef9aa6256c388191b92abae017fad985`) was
verified **disabled**. The older XP Luna and RiceBowl Roadmap automation tasks
were also disabled. This resolves the previously documented *scheduled*
merge-writer overlap; it does not prevent other live development chats
from pushing to their own branches. A file lease requires fresh head/base
checks before every write, and only Integration merges to `main`.
Other active automations target separate repositories and are not treated
as RiceBowl merge approval.

## Reporting format

Report **merged into main**, **implemented on branch**, **CI pass**,
**CI fail**, **pending**, and **on-device unverified** as separate states.
Include stable PR URLs, exact head/main SHAs and GitHub Actions run links.
After each integration, update the dependency graph from *live* GitHub data
instead of copying this snapshot.
