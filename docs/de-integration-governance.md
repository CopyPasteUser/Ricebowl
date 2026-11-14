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

## Live integration dependency graph (snapshot: 2026-11-14)

> This snapshot reflects GitHub refs checked on 14 November 2026, not the
> previous 13 November PR stack. [Issue #360](https://github.com/CopyPasteUser/Ricebowl/issues/360)
> is the coordination log; check it and live refs before each mutation.

```text
main @ 559f800ead46ff60c6551624734d4bbe47ddf667
├── #366 Run caret + modal keyboard handover
│   fix/luna-run-pointer-caret-20261114 [DRAFT, Native FAIL on prior head;
│   latest head 153660159ed65cdd352b316b30ec23dd12814fb0 pending CI]
├── Core — sprint/de-core-focus-20261114 [planned; branch not present at preflight]
├── Desktop — sprint/de-desktop-files-20261114 [planned; branch not present]
└── System — sprint/de-system-portals-20261114 [planned; branch not present]
```

Exactly one PR was open at the preflight: **#366**. The older #342, #343,
#349, #352, #353, #355, #356, #357 and #361 PRs were **closed, not merged**.
Do not represent them as active stacks or reopen/rebase them automatically.
Core focus issue #328 and strict portal issue #304 remain open. The new sprint
branches above are assigned work scopes, **not** evidence of current implementation.

PR #366 owns its four original paths: `WAYLAND_XP_LUNA_PARITY.md`,
`components/riceplate-wayland/src/luna_dialog.rs`, shared
`components/riceplate-wayland/src/main.rs` and
`scripts/smoke_riceplate_native.sh`. On `2c63c8f6`, exact-head
[Tests](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43577923669)
passed but [Native](https://github.com/CopyPasteUser/Ricebowl/actions/runs/43577923661)
failed: the real virtual keyboard delivered `Z` after the pointer click,
then the screenshot restoration comparison found 130 changed pixels against
its <8-pixel acceptance bound. This does **not** prove a compositor focus
regression; earlier heads had separate focus acquisition failures. Subsequent
commits `78cb5a888044` and `153660159ed6` changed shared files during
the review preflight. The integration lane aborted its own proposed write
instead of racing the head, and requested exclusive handoff in #366.

### Current merge order and blockers

1. **PR #366:** wait for the *new* exact head, inspect complete diff,
   running Native + Tests results and real pointer, keyboard, restoration
   evidence. Do not equate `mergeable` with approved and do not merge while
   Draft or a relevant gate is red.
2. **Core:** a new owner-scoped PR for actual seat/keyboard focus and window
   lifecycle behavior. Require compositor focus return-to-client evidence,
   not just a Rust algorithm or wallpaper pixels. A shared `main.rs` caller
   requires an explicit single-file integration lease.
3. **Desktop:** an independently testable file inventory may land before
   focus UI only if no implicit focus dependency is hidden. Desktop keyboard
   UI, file actions and RiceField handoff must await the accepted Core API.
4. **System:** safe isolated portal/session changes may land independently,
   only with strict ScreenCast fail-closed behavior and relevant session
   workflow coverage. No host-wide or XFCE state changes.
5. **Every candidate:** check base and head anew; review owner boundaries,
   full diff, exact-head CI, unresolved threads, and any automation overlap;
   merge only with `expected_head_sha`. Reverify every new `main` commit
   before another merge.

A new PR that touches the same shared path as another active PR must be
re-scoped or serialized. Handoff comments cannot act as an atomic lock.

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

## Immediate coordination risk: scheduled automation

An existing enabled automation titled **RiceBowl Wayland weiterentwickeln**
also scans `main`, comments on PRs and may create/merge feature branches.
Its latest verified run occurred on 2026-11-14; its saved instructions
still permit opening branches **and merging PRs**, conflicting with this
contract's sole merge authority. The integration lane documented the risk in
issue #360 and did **not** alter the automation. Before concurrent writes,
the owner/operator must restrict the automation to an explicitly disjoint
lane with no `main` merges or pause its GitHub writes. A written governance
rule alone cannot enforce the lock.

## Reporting format

Report **merged into main**, **implemented on branch**, **CI pass**,
**CI fail**, **pending**, and **on-device unverified** as separate states.
Include stable PR URLs, exact head/main SHAs and GitHub Actions run links.
After each integration, update the dependency graph from *live* GitHub data
instead of copying this snapshot.
