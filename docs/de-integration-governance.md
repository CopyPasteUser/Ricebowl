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

## Live integration dependency graph (snapshot: 2026-11-13)

```text
main (verified baseline c9373bd2)
├── #359 seat-owned input / Show Desktop (Draft; shared main.rs)
├── #342 desktop focus (Draft, native compositor focus gate FAIL)
│   └── #355 XDG Desktop/RiceField (Draft, native gate FAIL)
│       └── #356 inotify desktop refresh (Draft; stacked on #355)
├── #343 window actions (Draft, CI FAIL)
│   └── #352 taskbar follow-up (Draft, CI PASS on own head; parent FAIL)
├── #349 Start/All Programs (Draft, CI FAIL)
│   └── #353 Start menu follow-up (Draft, native keyboard FAIL)
├── #357 strict GLES2/PipeWire portal CI (Draft, new system lane)
├── #354 Control Panel/System UX (Draft, Tests + Wayland PASS;
│    native capture covered by Wayland workflow; review still required)
├── #337 recents roadmap (Draft, branch diverged; scope must be cleaned)
└── #358 integration contract (Draft; docs only)
```

See [issue #360](https://github.com/CopyPasteUser/Ricebowl/issues/360) for live cross-lane handoffs and CI triage. This graph must be refreshed whenever a concurrent agent opens a new PR.

The graph describes actual *PR base branches* as observed on this date, not
permanent ownership. Every entry is conditional on current refs and checks.
`mergeable=true` does **not** mean release-ready; draft, failing, stale,
missing or incorrectly scoped checks are independent blockers.

### Merge order and explicit blocking conditions

1. **Core gate:** #342 must pass a real labwc keyboard focus/return-to-client
   proof on a supported compositor, not just a Rust unit test or popup pixels.
   Legacy compositor limitations must be clearly classified and supported via
   an honest fallback or explicit minimum-version requirement.
2. **Window gate:** #343 must pass exact-head Rust/Clippy, Python,
   native compositor and Wayland session tests. Then rebase/retarget #352,
   revalidate and integrate.
3. **Desktop gate:** only after #342 is integrated, retarget #355 onto updated
   `main`; verify file interaction/focus, read-only/denied paths, output
   unplug, cleanup and native compositor tests.
4. **Menu gate:** fix #349's failed Tests/Native workflows and #353 keyboard
   Escape behavior; integrate parent before follow-up.
5. **Independent UI:** #354 may undergo review independently; functional DE
   integration takes precedence over visual fidelity. Do not merge merely
   because two workflows are green.
6. **Docs cleanup:** #337 is not automatically safe because its title says
   `docs`; compare the full PR against the current `main` and isolate
   only the intended roadmap change before integration.

Do not merge any of these just to shorten the queue. Preserve a passing
`main` until a candidate meets its own acceptance contract.

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
Its last confirmed run on 2026-11-13 performed PR #342 CI triage. The
integration lane must inspect automation-originated PRs and avoid parallel
writes to its active branches; only the owner/operator may change the
automation schedule or instructions. Before long parallel sprints, either
give that automation a disjoint ownership lane or explicitly suspend its
repository writes. A written governance rule alone cannot enforce the lock.

## Reporting format

Report **merged into main**, **implemented on branch**, **CI pass**,
**CI fail**, **pending**, and **on-device unverified** as separate states.
Include stable PR URLs, exact head/main SHAs and GitHub Actions run links.
After each integration, update the dependency graph from *live* GitHub data
instead of copying this snapshot.
